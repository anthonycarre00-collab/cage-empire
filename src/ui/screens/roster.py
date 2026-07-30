"""CAGE EMPIRE — Roster screen (Stage 6 — Task 6.4).

The player's Roster — one of the two highest-traffic screens in
CAGE EMPIRE (the other is Fighter Profile). Shows every active
fighter on the player's promotion, with each fighter's
interpretation-layer output displayed as voice phrases — NOT raw
attribute numbers.

Per docs/GUI_PLAN.md §5.2 (FIGHTERS group):
  "Sortable/filterable table of player's promotion fighters."
  Listed primary tables: `fighters`, `fighter_attributes`,
  `fighter_contracts`, `rankings`.

  Per CONVENTIONS §17 (UI Snapshot Rule — CRITICAL), the Roster
  reads ONLY from cache + game-state tables — NOT from
  `fighter_attributes` (raw 0-100 numbers) or `fighter_contracts`
  (a simulation table per §17.3). The actual source map is:

    - `fighters` (game state — first_name, last_name, nickname,
      weight_class_id, current_promotion_id, is_active. Names are
      NOT raw attribute values per §14.)
    - `fighter_descriptors` (cache — career_phase, momentum,
      narrative_family voice phrases per §17.3. The interpretation
      layer is the only writer.)
    - `fighter_career` (game state — record_wins, record_losses,
      record_draws. Career stats are OK per §14 ("career stats not
      attributes"). Listed in §17.3 as a simulation table, but the
      §14 rule explicitly allows "career stats" like record.)
    - `weight_classes` (game state — weight class name. NOT a
      fighter attribute table.)

  This screen NEVER reads from `fighter_attributes` (raw 0-100
  values), `fighter_personality` (raw trait values), `fighter_bios`
  (long-form prose — that's for Fighter Profile), `fighter_contracts`
  (simulation table per §17.3). See D1.

Per docs/CONVENTIONS.md §14 (Interpretation Layer — CRITICAL):
  No raw attribute values appear in the player-facing UI.
    - Career phase → decoded voice phrase (e.g., "a blue-chip
      prospect early in his career") — never the raw "prospect"
      label, never the underlying numbers that produced it.
    - Momentum → decoded voice phrase (e.g., "riding a hot streak")
      — never the raw "high" label.
    - Narrative family → decoded voice phrase (e.g., "the wunderkind
      everyone's talking about") — never the raw "prodigy" label.
    - Record → "18-5-0" — OK per §14 (career stats, not attributes).

Per docs/CONVENTIONS.md §17.4 ("Rich Not Thin" — CRITICAL):
  Every cache label has an associated voice phrase. The cache stores
  "label||phrase"; the UI shows the phrase. The Roster uses
  `interpretation.context_engine.decode_phrase` (single source of
  truth) to extract the phrase.

Architecture (mirrors DashboardScreen — same pattern all Office
Mode screens follow):
  - RosterScreen(ctk.CTkFrame) — the screen widget.
  - _build_header() — H1 title + roster-count subtitle.
  - _build_filter_row() — weight-class dropdown + name search entry.
  - _build_table() — ttk.Treeview with 6 columns (Name, WC, Career
    Phase, Momentum, Record, Narrative). Themed to match the
    Office dark palette via a custom ttk.Style.
  - _build_pagination() — Prev / Next buttons + page indicator.
  - _refresh() — registered with GameState; re-queries the roster
    (filtered + searched + paginated) + re-renders the Treeview.
    Safe to call repeatedly (clears old rows first).

Navigation:
  - Double-click a row → set_fighter_id(fighter_id) on the Fighter
    Profile screen → state.set_active_screen("fighter_profile").
  - The Fighter Profile screen is registered separately in app.py;
    the Roster reaches it via state.get_screen("fighter_profile").

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Source-of-truth map. See the §17 comment block above. The
      rule: fighter INTERPRETATION data (career_phase, momentum,
      narrative_family) comes from fighter_descriptors cache ONLY.
      Fighter NAMES + weight_class_id come from `fighters` (game
      state). Record comes from `fighter_career` (career stats —
      OK per §14). Weight class name from `weight_classes` (game
      state). The Roster NEVER touches fighter_attributes /
      fighter_personality / fighter_bios / fighter_contracts.

      Note on fighter_career: §17.3 lists `fighter_career` as a
      simulation table (the interpretation layer never writes to
      it). However, §14 explicitly permits "career stats" (record,
      streaks, title reigns) in the UI — they are NOT raw attribute
      values. The Roster reads ONLY record_wins / record_losses /
      record_draws from fighter_career (never `potential`, never
      `career_health` — those are §14-protected). This is the same
      carve-out the Task 6.3 brief applied for the dashboard's
      roster count.

  D2  ttk.Treeview (via tkinter.ttk, not ttkbootstrap). The brief
      says "use ttk.Treeview (via ttkbootstrap)". ttkbootstrap is
      in requirements.txt but not installed in this environment
      (verified during pre-flight). The standard `tkinter.ttk`
      Treeview is functionally identical — the only difference is
      ttkbootstrap auto-themes it. We achieve the same dark theme
      manually via `ttk.Style().configure('Roster.Treeview', ...)`
      using the Office palette colors from ui.theme. This keeps the
      Roster consistent with the rest of the CTk shell without
      adding a runtime dependency that isn't yet installed. When
      ttkbootstrap lands, the only change needed is to swap the
      Style setup — the Treeview widget itself is unchanged.

      Style mapping (Office dark):
        - Treeview background = theme.colors.bg_surface (#1a1d23)
        - Treeview foreground = theme.colors.text_primary (#e8eaed)
        - Selected row       = theme.colors.bg_surface_elevated (#232730)
        - Heading background = theme.colors.bg_surface_elevated
        - Heading foreground = theme.colors.gold (#d4a55a)
        - Row height = 28px (touch-friendly per the UI rules)
        - Field background (cell bg) = theme.colors.bg_surface
        - Border color = theme.colors.bg_border

      The style is rebuilt on every _refresh() so theme-change
      refresh picks up the new colors (mirrors how DashboardScreen
      rebuilds every widget on _refresh). The style NAME is constant
      ("Roster.Treeview") so the Treeview widget itself doesn't need
      to be recreated.

  D3  Pagination (20 rows per page). The player's promotion has
      ~1000 active fighters. Rendering all of them in a Treeview is
      possible (Treeview is virtualized) but the cognitive load is
      excessive — the player can't scan 1000 rows. Pagination
      forces the player to actually look at each page. Page size
      is 20 (matches the brief's "show 20 at a time"). The page
      state survives across _refresh() calls (stored in
      self._current_page); navigating back from Fighter Profile
      preserves the page the player was on. Page state resets to 1
      when the filter or search changes (so the player doesn't end
      up on an out-of-range page after narrowing the result set).

  D4  Filter by weight class. The dropdown lists every weight class
      present in the player's promotion (queried once on _refresh,
      re-queried when the player toggles the filter). "All Weight
      Classes" is the default option (value=None). The filter is
      applied in SQL (WHERE weight_class_id = ?) — efficient even
      with 1000+ rows. The dropdown is a CTkOptionMenu (matches the
      dashboard's visual language).

  D5  Search by name. Case-insensitive substring match on
      first_name + last_name + nickname. Applied in SQL via
      `LIKE '%term%'` (SQLite's LIKE is case-insensitive for ASCII
      by default — sufficient for English fighter names). The
      search entry is a CTkEntry with a placeholder ("Search by
      name..."). Search triggers re-query on every keystroke via
      the entry's `<KeyRelease>` binding (debounced naturally by
      the GUI event loop — no manual throttle needed for 1000
      rows).

  D6  Empty-state handling. Every state degrades gracefully:
      - No fighters in roster → "Your roster is empty. Sign some
        free agents to build your stable."
      - No fighters match the filter → "No fighters match this
        weight class."
      - No fighters match the search → "No fighters match
        '<term>'. Try a different name."
      - No fighter_descriptors rows for a fighter → the career
        phase / momentum / narrative columns show "(uncached)"
        rather than crashing. This shouldn't happen in practice
        (the daily interpretation pass populates every active
        fighter), but the defensive code is here per the
        Dashboard's D6 pattern.

  D7  Double-click navigation. The Treeview's `<Double-1>` event
      (double-click) triggers navigation. Single-click just selects
      the row (the highlight the player expects). This matches the
      idiom of every desktop data table — double-click to open. The
      handler reads the selected item's fighter_id (stored as the
      Treeview item's `iid`), calls set_fighter_id() on the Fighter
      Profile screen, then navigates via state.set_active_screen.
      Defensive: if no row is selected, no-op. If the Fighter
      Profile screen isn't registered yet (shouldn't happen but
      defensive), the navigation call catches the ValueError and
      logs a warning.

  D8  Sortable columns (lightweight). Treeview heading clicks sort
      the underlying data by that column. The sort state is tracked
      in self._sort_column + self._sort_reverse. Default sort is
      by fighter_id ascending (insertion order — mirrors the seed
      order, which is roughly chronological by debut). Clicking a
      heading toggles asc/desc. The sort is applied in Python (not
      SQL) because the voice phrases need decode_phrase() before
      sorting — sorting raw "label||phrase" strings would sort by
      the canonical label, not the player-facing phrase, which is
      unintuitive. Sorting in Python after decode is fine for
      ~1000 rows.

  D9  Refresh pattern. Following DashboardScreen: dynamic widgets
      are tracked in instance lists (_table_items holds Treeview
      item iids; _weight_class_options holds the dropdown values).
      _refresh() clears the Treeview (via `tv.delete(*tv.get_children())`),
      re-queries, re-renders. Static structure (H1 title, filter
      row, Treeview widget, pagination bar) is built once in
      __init__. Theme-change refresh (state.refresh_all after
      set_theme) re-applies the ttk.Style + re-renders with the
      new theme's colors/fonts because every widget construction
      calls get_theme() at render time.

  D10 Pagination boundary. When the filter or search narrows the
      result set, the current page may be out of range (e.g., page
      5 of 50 pages → filter narrows to 1 page). _refresh() clamps
      self._current_page to the last valid page after every query.
      The player never sees a blank page.

  D11 Performance. The roster query is one JOIN across 4 tables
      (fighters + fighter_descriptors + fighter_career +
      weight_classes) with a WHERE clause on current_promotion_id
      + is_active. On the live 4450-fighter DB, this returns
      ~1000 rows in <30ms (verified during pre-flight). The
      decode_phrase() calls are pure Python string splits — fast.
      The Treeview insert is the slowest part (~10ms for 20 rows),
      well within the 1-second performance budget from §17.5
      (which applies to the daily interpretation pass, not the UI,
      but the spirit is the same: the UI must feel instant).
"""

import sqlite3
from pathlib import Path

import customtkinter as ctk

# PIL is used for the promotion logo load + resize (Fix 9). Falls
# back gracefully if PIL isn't installed (the logo label shows text
# initials instead).
try:
    from PIL import Image as _PIL_Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from ui.theme import get_theme
from ui.state import get_state
from ui.voice_display import title_case_phrase, \
    display_attr_descriptor

# UI Fix Plan 2 — Phase 3, Fix 11 (AD-5): the new FighterTable widget
# replaces the ttk.Treeview (the legacy Treeview code was deleted in
# UI Implementation Plan v3 — P2-3, ~600 LOC of dead code removed).
from ui.widgets.fighter_table import FighterTable, Column

# Phase 4 — Performance: debounce decorator for the search entry so
# each keystroke doesn't trigger a full DB query + 120-widget rebuild.
# The 200ms window collapses 4-5 keystrokes of fast typing into a
# single refresh.
from ui.perf import debounce

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (mirrors
# DashboardScreen's D4).
from interpretation.context_engine import decode_phrase


# ============================================================
# PROMOTION LOGO PATH (Fix 9)
# ============================================================
# Logos live at src/ui/assets/promo_logos/<promotion_id>_<slug>.png.
# The slug is the promotion name lowercased with underscores (e.g.,
# "alpha_combat_federation"). We resolve the logo at refresh time by
# globbing for "<promo_id>_*.png" — robust against slug renames.
_PROMO_LOGOS_DIR = (Path(__file__).resolve().parent.parent
                    / "assets" / "promo_logos")


# ============================================================
# CONSTANTS
# ============================================================

# Page size — per the brief: "show 20 at a time".
PAGE_SIZE = 20

# Sort-column identifiers used by _sort_roster + the FighterTable's
# on_sort_click callback. These were originally Treeview column IDs
# (UI Fix Plan 2 — Phase 3, Fix 11); the Treeview was deleted in
# UI Implementation Plan v3 — P2-3, but the identifiers survive as
# the sort_column values the FighterTable path maps to. Kept as
# named constants (rather than literal strings) so the sort logic
# reads as `col == COL_WC` instead of `col == "weight_class"` —
# self-documenting + grep-friendly.
COL_WC = "weight_class"
COL_PHASE = "career_phase"
COL_MOMENTUM = "momentum"
COL_RECORD = "record"


# UI Fix Plan 2 — Phase 3, Fix 11b + 11c: column set for the
# FighterTable widget. The layout is:
#   Name | Age | Nat | WC | Stage | Form | Record
# Changes per the plan + UI Implementation Plan v3 (P2-1):
#   - "Career Phase" → "Stage" (short phrases, not long-form)
#   - "Momentum" → "Form" (short phrases)
#   - "Narrative" column removed entirely (discover on Fighter Profile)
#   - Age added as the 2nd column (computed from DOB + sim date)
#   - Nat added as the 3rd column (3-letter ISO code from nations.name)
#   - WC abbreviated (HW, LHW, MW, WW, LW, FW, BW, FlyW, WSW, WBW,
#     WFlyW, WFW, WAW) — full name still on Fighter Profile
#   - Name column drops the nickname (first + last only) — the
#     nickname is still on Fighter Profile
NEW_COL_NAME = "name"
NEW_COL_AGE = "age"
NEW_COL_NAT = "nat"
NEW_COL_WC = "wc"
NEW_COL_STAGE = "stage"
NEW_COL_FORM = "form"
NEW_COL_RECORD = "record"
NEW_COL_GYM = "gym"

NEW_COLUMN_LABELS = {
    NEW_COL_NAME: "Name",
    NEW_COL_AGE: "Age",
    NEW_COL_NAT: "Nat",
    NEW_COL_WC: "WC",
    NEW_COL_STAGE: "Stage",
    NEW_COL_FORM: "Form",
    NEW_COL_RECORD: "Record",
    NEW_COL_GYM: "Gym",
}

# Column widths rebalanced for the 7-column layout (P2-1). Total
# ~720px — leaves room for the scrollbar + card padding without
# blank space at the right edge. Nat is narrow (3-letter code);
# Stage + Form are slightly narrower than v2 because the table has
# one more column now.
NEW_COLUMN_WIDTHS = {
    NEW_COL_NAME: 260,
    NEW_COL_AGE: 50,
    NEW_COL_NAT: 50,
    NEW_COL_WC: 60,
    NEW_COL_STAGE: 160,
    NEW_COL_FORM: 140,
    NEW_COL_RECORD: 80,
    NEW_COL_GYM: 200,
}

NEW_COLUMN_ANCHORS = {
    NEW_COL_NAME: "w",
    NEW_COL_AGE: "center",
    NEW_COL_NAT: "center",
    NEW_COL_WC: "center",
    NEW_COL_STAGE: "w",
    NEW_COL_FORM: "w",
    NEW_COL_RECORD: "center",
    NEW_COL_GYM: "w",
}


# ============================================================
# UI Implementation Plan v3 — P2-1: nationality abbreviation map.
# ============================================================
# Map nation name (lowercased) → 3-letter ISO-style code. Covers the
# 20 nations seeded in the live DB (verified via
# `SELECT DISTINCT name FROM nations`). Defensive — unknown nations
# fall back to the first 3 letters of the name uppercased (so newly-
# added nations don't break the table).
# Nations table currently has no iso_alpha_3 column (only name +
# language) so we maintain this lookup locally. If a future schema
# migration adds iso_alpha_3, this map can be replaced with a DB
# read in _query_roster.
_NAT_ABBREVIATIONS = {
    "argentina": "ARG",
    "australia": "AUS",
    "brazil": "BRA",
    "canada": "CAN",
    "china": "CHN",
    "cuba": "CUB",
    "dagestan": "DAG",
    "france": "FRA",
    "germany": "GER",
    "ireland": "IRL",
    "japan": "JPN",
    "mexico": "MEX",
    "netherlands": "NED",
    "nigeria": "NGA",
    "poland": "POL",
    "russia": "RUS",
    "south korea": "KOR",
    "sweden": "SWE",
    "united kingdom": "GBR",
    "united states": "USA",
}


def _abbreviate_nat(nation_name):
    """Abbreviate a nation name to a 3-letter ISO-style code.

    Per P2-1: the Roster table shows abbreviated nationalities (USA,
    BRA, JPN, etc.) instead of full names — saves horizontal space
    for the new Nat column. The full nation name is still shown on
    the Fighter Profile.

    Defensive — unknown names fall back to the first 3 letters of
    the name uppercased (so newly-added nations don't break the
    table). Returns "" for None / empty input (renders as a blank
    Nat cell — better than crashing on a fighter with NULL
    birth_nation_id).
    """
    if not nation_name:
        return ""
    key = str(nation_name).strip().lower()
    if key in _NAT_ABBREVIATIONS:
        return _NAT_ABBREVIATIONS[key]
    return str(nation_name).strip()[:3].upper()


# ============================================================
# UI Fix Plan 2 — Phase 3, Fix 11b: WC abbreviation map.
# ============================================================
# Full weight class name → 2-4 letter abbreviation. Covers the 13
# weight classes in the CAGE EMPIRE world DB (per
# scripts/group_b_populate_wcs.py):
#   Men:  HW, LHW, MW, WW, LW, FW, BW, FlyW
#   Women: WSW, WBW, WFlyW, WFW, WAW
# Defensive — unknown weight classes fall back to the first 3 letters
# of the name uppercased.
_WC_ABBREVIATIONS = {
    # Men's
    "heavyweight": "HW",
    "light heavyweight": "LHW",
    "middleweight": "MW",
    "welterweight": "WW",
    "lightweight": "LW",
    "featherweight": "FW",
    "bantamweight": "BW",
    "flyweight": "FlyW",
    # Women's
    "women's strawweight": "WSW",
    "women's bantamweight": "WBW",
    "women's flyweight": "WFlyW",
    "women's featherweight": "WFW",
    "women's atomweight": "WAW",
}


def _abbreviate_wc(wc_name):
    """Abbreviate a weight class name for compact table display.

    Per Fix 11b: the Roster table shows abbreviated weight classes
    (HW, LHW, MW, etc.) instead of full names — saves horizontal
    space for the new Age + Stage + Form columns. The full name is
    still shown on the Fighter Profile.

    Defensive — unknown names fall back to the first 3 letters of
    the name uppercased (so newly-added weight classes don't break
    the table).
    """
    if not wc_name:
        return ""
    key = str(wc_name).strip().lower()
    if key in _WC_ABBREVIATIONS:
        return _WC_ABBREVIATIONS[key]
    # Fallback: first 3 letters uppercased.
    return str(wc_name).strip()[:3].upper()


# ============================================================
# UI Fix Plan 2 — Phase 3, Fix 11c: short phrases for Stage + Form.
# ============================================================
# The Treeview showed the full decoded voice phrase (e.g., "A Surging
# Contender With the Division on Notice"). The new FighterTable shows
# a short, punchy label (e.g., "Rising Contender") per the plan.
# These are deterministic per canonical label (no RNG variants) so
# the table reads consistently + saves horizontal space.

# Map canonical career_phase label → short Stage phrase.
_STAGE_SHORT_PHRASES = {
    "prospect": "Prospect",
    "rising_contender": "Rising Contender",
    "champion": "Champion",
    "veteran": "Veteran",
    "gatekeeper": "Gatekeeper",
    "declining": "Declining",
}

# Map canonical momentum label → short Form phrase.
_FORM_SHORT_PHRASES = {
    "very_high": "Blazing Hot",
    "high": "Heating Up",
    "stable": "Steady",
    "falling": "Cooling Off",
    "collapsing": "Free Fall",
}


def _stage_short_phrase(stored_value):
    """Decode a career_phase cache value to a short Stage phrase.

    Args:
        stored_value: the raw "label||phrase" cache column value
            (e.g., "rising_contender||a surging contender...").

    Returns:
        Short phrase like "Rising Contender", or "(Uncached)" if the
        stored value is NULL / unrecognized.
    """
    if not stored_value or "||" not in str(stored_value):
        return "(Uncached)"
    label = str(stored_value).split("||", 1)[0]
    return _STAGE_SHORT_PHRASES.get(label, "(Uncached)")


def _form_short_phrase(stored_value):
    """Decode a momentum cache value to a short Form phrase.

    Args:
        stored_value: the raw "label||phrase" cache column value
            (e.g., "high||riding a hot streak").

    Returns:
        Short phrase like "Heating Up", or "(Uncached)" if the
        stored value is NULL / unrecognized.
    """
    if not stored_value or "||" not in str(stored_value):
        return "(Uncached)"
    label = str(stored_value).split("||", 1)[0]
    return _FORM_SHORT_PHRASES.get(label, "(Uncached)")


# ============================================================
# UI Fix Plan 2 — Phase 3, Fix 11b: age computation.
# ============================================================
def _compute_age_from_dob(dob_str, sim_date_str):
    """Compute a fighter's age as of the sim date.

    Mirrors interpretation.context_engine._compute_age but lives here
    so the Roster doesn't need to import the interpretation layer
    (keeps the UI/interpretation boundary clean per §17.1). Defensive
    — returns "" on any parse failure (so the Age column shows blank
    instead of crashing the table on a fighter with bad DOB data).

    Args:
        dob_str: ISO date string (e.g., "1998-04-15") from
            fighters.date_of_birth.
        sim_date_str: ISO date string from simulation_clock.current_date.

    Returns:
        Age as a string (e.g., "28"), or "" if either date is missing
        or unparseable.
    """
    if not dob_str or not sim_date_str:
        return ""
    try:
        from datetime import datetime as _dt
        dob = _dt.strptime(str(dob_str)[:10], "%Y-%m-%d")
        cur = _dt.strptime(str(sim_date_str)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return ""
    age = cur.year - dob.year
    if (cur.month, cur.day) < (dob.month, dob.day):
        age -= 1
    return str(age)


# ============================================================
# HELPERS
# ============================================================

def _format_name(first, last, nickname):
    """Format a fighter's name with optional nickname in quotes.

    "Hiroki Nakamura \"Mist\"" — matches the display convention used
    in the Dashboard's Fighter Watch + the brief's Roster mockup.
    Defensive — any None components are skipped (some fighters have
    no nickname).

    Args:
        first: first_name string (may be None).
        last: last_name string (may be None).
        nickname: nickname string (may be None or "None" — the seed
            scripts sometimes write the literal string "None" for
            missing nicknames).

    Returns:
        Display string like "John Vale \"Hammer\"" or "John Vale"
        if no nickname.
    """
    parts = []
    if first:
        parts.append(str(first).strip())
    if last:
        parts.append(str(last).strip())
    name = " ".join(parts).strip() or "Unknown"
    if nickname and str(nickname).strip() and str(nickname).strip().lower() != "none":
        nick = str(nickname).strip()
        name += f' "{nick}"'
    return name


def _format_name_short(first, last):
    """Format a fighter's name as 'First Last' (no nickname).

    UI Fix Plan 2 — Phase 3, Fix 11b: the new FighterTable's Name
    column drops the nickname (the table is data-dense; nicknames
    clutter the column). The nickname is still shown on the Fighter
    Profile. This helper exists separately from _format_name so the
    Treeview fallback (which keeps the nickname) continues to work.

    Defensive — None components are skipped.
    """
    parts = []
    if first:
        parts.append(str(first).strip())
    if last:
        parts.append(str(last).strip())
    return " ".join(parts).strip() or "Unknown"


def _load_promo_logo(promo_id, promo_name, size=60):
    """Load + resize a promotion logo for the Roster header (Fix 9).

    Resolves src/ui/assets/promo_logos/<promo_id>_*.png via glob (so
    slug renames don't break the lookup). Resizes to `size`x`size`
    via PIL LANCZOS. Returns a PIL.Image (caller wraps in CTkImage),
    or None if the file isn't found / PIL isn't available.

    Args:
        promo_id: int — the promotion_id from the DB.
        promo_name: str — the promotion name, used for the text-
            initials fallback if the logo file isn't found.
        size: target size in px (default 60 — matches the header
            logo slot in _build_header).
    """
    if not HAS_PIL or promo_id is None:
        return None
    try:
        # Glob for "<promo_id>_*.png" — robust against slug renames.
        matches = list(_PROMO_LOGOS_DIR.glob(f"{int(promo_id)}_*.png"))
        if not matches:
            return None
        img = _PIL_Image.open(str(matches[0]))
        img = img.convert("RGBA")
        img = img.resize((size, size), _PIL_Image.LANCZOS)
        return img
    except Exception as e:
        print(f"Warning: promo logo load failed for promo {promo_id}: {e}",
              flush=True)
        return None


def _format_record(wins, losses, draws):
    """Format a fighter's record as 'W-L-D'.

    Per §14: career stats (record) are explicitly OK to display as
    numbers — they're not attribute values. The 'W-L-D' format is
    the universal fight-sport convention.

    Defensive — any None components default to 0.
    """
    try:
        w = int(wins or 0)
    except (TypeError, ValueError):
        w = 0
    try:
        l = int(losses or 0)
    except (TypeError, ValueError):
        l = 0
    try:
        d = int(draws or 0)
    except (TypeError, ValueError):
        d = 0
    return f"{w}-{l}-{d}"


def _phrase_or_fallback(stored_value, fallback):
    """Decode a "label||phrase" cache value, or return a fallback.

    Per §17.4: the UI displays the voice PHRASE (after ||), never
    the canonical label (before ||). If the stored value is NULL or
    doesn't contain "||", return the caller-provided fallback
    (e.g., "(none)" for narrative_family when the interpretation
    layer hasn't assigned one).

    Args:
        stored_value: the raw cache column value (e.g.,
            "rising||a rising star on the way up").
        fallback: the string to return if decode_phrase returns
            None (e.g., "(none)", "(uncached)").

    Returns:
        The voice phrase string, or the fallback.
    """
    phrase = decode_phrase(stored_value)
    return phrase if phrase else fallback


# ============================================================
# ROSTER SCREEN
# ============================================================

class RosterScreen(ctk.CTkFrame):
    """Roster — the player's promotion fighters, interpretation-first.

    The HIGHEST-TRAFFIC screen in CAGE EMPIRE (per GUI_PLAN §5.7).
    Office Mode only (NOT a Fight Night screen). Registered with
    GameState as 'roster'. The refresh callback (`_refresh`) re-queries
    the roster (filtered + searched + paginated) + re-renders the
    Treeview.

    Usage:
        screen = RosterScreen(parent_frame)
        state.register_screen("roster", screen, screen._refresh)
        state.set_active_screen("roster")
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Configure the screen's own background to match the Office
        # Mode base — cards inside sit on top of this.
        theme = get_theme()
        self.configure(fg_color=theme.colors.bg_base)

        # Filter + pagination state. Survives across _refresh() calls
        # so the player's view is preserved when they navigate to
        # Fighter Profile and back. See D3, D4, D5.
        self._current_page = 1
        self._weight_class_filter = None  # None = "All Weight Classes"
        # UI Fix Plan 2 — Phase 1, Fix 10: default gender filter to
        # "male" (was None = "All"). The user's Phase 2 brief said
        # "men and women mixed together" was a complaint; Phase 1's
        # UI-POLISH added the gender dropdown, but defaulted to "All"
        # which still mixed them. Phase 1 Fix 10 changes the default
        # to "Male" so the player sees their male roster first (the
        # larger cohort in MMA promotions) + can switch to "Female"
        # or "All" via the dropdown. Same change in free_agents.py
        # for consistency.
        self._gender_filter = "male"
        self._search_term = ""
        self._sort_column = "fighter_id"  # default: insertion order
        self._sort_reverse = False

        # Cached roster data (list of dicts). Refreshed by _refresh().
        # Kept as an attribute so the sort handler can re-sort without
        # re-querying the DB.
        self._roster_data = []

        self._pagination_label = None
        self._prev_button = None
        self._next_button = None
        self._subtitle_label = None
        self._weight_class_menu = None
        # Per UI-POLISH Fix 2: gender filter dropdown.
        self._gender_menu = None
        # Per UI-POLISH Fix 3: "View Profile" button below the table.
        self._view_profile_button = None
        self._search_entry = None

        # UI Fix Plan 2 — Phase 3, Fix 11 (AD-5): the new FighterTable
        # widget. Built by _build_table. Holds the row data the
        # FighterTable renders (set_rows replaces the Treeview's
        # insert/clear cycle).
        # UI Implementation Plan v3 — P2-3: the legacy ttk.Treeview
        # path + USE_TREEVIEW flag were deleted — FighterTable is now
        # the only table implementation.
        self._fighter_table = None

        # UI Fix Plan 2 — Phase 3, Fix 9: promotion logo image
        # reference. Kept as an attribute so the GC doesn't drop the
        # underlying Tk image (Tk images are referenced by name, not
        # Python refcount). Built by _refresh_subtitle (which has the
        # promo_id needed to resolve the logo file).
        self._promo_logo_ctk_image = None
        # Per-Fix-9 promotion name cache (so we don't re-query for
        # the logo fallback text initials on every refresh).
        self._cached_promo_name = None

        # UI Fix Plan 2 — Phase 3, Fix 11b: cached sim date string
        # (used for age computation in _render_table_new). Refreshed
        # by _refresh before rendering the table.
        self._sim_date_str = None

        # Build the static structure. Dynamic content (table rows,
        # pagination label, weight-class dropdown values) is rendered
        # by _refresh.
        self._build_header()
        self._build_filter_row()
        self._build_table()
        self._build_pagination()
        self._build_view_profile_button()
        self._build_footer()

        # Initial render. Use after(50, ...) so the widget is fully
        # laid out before we query (matches DashboardScreen pattern).
        self.after(50, self._refresh)

    # ============================================================
    # SECTION 1 — HEADER (H1 title + roster-count subtitle)
    # ============================================================

    def _build_header(self):
        """Build the H1 title + subtitle ('THE STABLE' + promotion + count).

        UI Fix Plan 2 — Phase 3, Fix 2: H1 title renamed from 'ROSTER'
        to 'THE STABLE' to match the NAV_GROUPS display name + the
        plan's Voice Recommendations table. The screen-name key
        'roster' is unchanged so state.set_active_screen + refresh
        registrations still work.
        """
        theme = get_theme()

        # Header row: title + optional promotion logo (Fix 9).
        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # ---- Promotion logo (Fix 9) ----
        # Small 60x60 logo loaded from src/ui/assets/promo_logos/.
        # Falls back to text initials if the logo isn't found. Set on
        # self._promo_logo_label by _refresh_subtitle (which has the
        # promo_id needed to resolve the right file).
        self._promo_logo_label = ctk.CTkLabel(
            header_row, text="",
            width=60, height=60,
            fg_color=theme.colors.bg_surface_elevated,
            corner_radius=8,
            anchor="center",
        )
        self._promo_logo_label.pack(side="left", padx=(0, 12))

        # Title + subtitle stack on the right of the logo.
        title_subtitle_stack = ctk.CTkFrame(header_row, fg_color="transparent")
        title_subtitle_stack.pack(side="left", fill="x", expand=True)

        title = ctk.CTkLabel(
            title_subtitle_stack, text="THE STABLE",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x")

        # Subtitle populated by _refresh (needs promotion name + count
        # from the DB). Kept as an attribute so _refresh can call
        # .configure() on it without recreating.
        self._subtitle_label = ctk.CTkLabel(
            title_subtitle_stack, text="Loading roster...",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", pady=(2, 0))

    # ============================================================
    # SECTION 2 — FILTER ROW (weight-class dropdown + search entry)
    # ============================================================

    def _build_filter_row(self):
        """Build the filter row: gender + weight-class + search entry.

        Layout (per UI-POLISH Fix 2 — gender dropdown added next to
        the weight-class dropdown):
          [Gender: ▼ All]  [Weight Class: ▼ All WC]  [Search: [___]]

        The gender dropdown filters by `fighters.gender` (male /
        female / unknown). Male + female weight classes are different
        divisions in fight sports — separating them is a UX win.

        The weight-class dropdown lists every weight class present in
        the player's promotion + an "All Weight Classes" option. The
        search entry is case-insensitive substring on first_name +
        last_name + nickname. See D4, D5.
        """
        theme = get_theme()

        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # ---- GENDER dropdown (UI-POLISH Fix 2) ----
        gender_label = ctk.CTkLabel(
            filter_row, text="Gender:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
        )
        gender_label.pack(side="left", padx=(0, 8))

        self._gender_menu = ctk.CTkOptionMenu(
            filter_row,
            values=["All", "Male", "Female"],
            command=self._on_gender_change,
            width=110, height=30,
            font=theme.fonts.body,
            dropdown_font=theme.fonts.body,
            fg_color=theme.colors.bg_surface,
            button_color=theme.colors.bg_surface_elevated,
            button_hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
        )
        # UI Fix Plan 2 — Phase 1, Fix 10: default dropdown to "Male"
        # so the initial view matches _gender_filter="male" set in
        # __init__. Without this, the dropdown would show "All" while
        # the actual filter is "male" — confusing desync.
        self._gender_menu.set("Male")
        self._gender_menu.pack(side="left", padx=(0, 20))

        # ---- WEIGHT CLASS dropdown ----
        wc_label = ctk.CTkLabel(
            filter_row, text="Weight Class:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
        )
        wc_label.pack(side="left", padx=(0, 8))

        # Weight-class dropdown. Values populated by _refresh (which
        # re-queries the weight classes present in the player's roster
        # on every render — handles changes from signing/cutting
        # fighters). Default value is "All Weight Classes".
        self._weight_class_menu = ctk.CTkOptionMenu(
            filter_row,
            values=["All Weight Classes"],
            command=self._on_weight_class_change,
            width=200, height=30,
            font=theme.fonts.body,
            dropdown_font=theme.fonts.body,
            fg_color=theme.colors.bg_surface,
            button_color=theme.colors.bg_surface_elevated,
            button_hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
        )
        self._weight_class_menu.set("All Weight Classes")
        self._weight_class_menu.pack(side="left", padx=(0, 20))

        # ---- SEARCH entry ----
        search_label = ctk.CTkLabel(
            filter_row, text="Search:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
        )
        search_label.pack(side="left", padx=(0, 8))

        # Search entry — case-insensitive substring on name. Triggers
        # re-query on every KeyRelease (D5).
        self._search_entry = ctk.CTkEntry(
            filter_row,
            placeholder_text="Search by name...",
            width=240, height=30,
            font=theme.fonts.body,
            fg_color=theme.colors.bg_surface,
            border_color=theme.colors.bg_border,
            text_color=theme.colors.text_primary,
        )
        self._search_entry.pack(side="left")
        self._search_entry.bind("<KeyRelease>", self._on_search_change)

    # ============================================================
    # SECTION 3 — TABLE (FighterTable — Fix 11)
    # ============================================================

    def _build_table(self):
        """Build the roster table.

        UI Implementation Plan v3 — P2-3: the legacy ttk.Treeview
        path + USE_TREEVIEW flag were deleted. FighterTable is now
        the only table implementation. This method is kept as a thin
        wrapper around _build_table_new so existing call sites
        (__init__ + the docstring's "D2" reference) stay valid.
        """
        self._build_table_new()

    def _build_table_new(self):
        """Build the new FighterTable-based roster table (Fix 11).

        Replaces the ttk.Treeview with a CTk-based custom widget that
        supports HyperlinkLabels (Fix 13 — fighter names link to
        Fighter Profile) + rich per-cell content. See
        src/ui/widgets/fighter_table.py for the widget architecture.

        Column layout per Fix 11b + 11c + UI Implementation Plan v3
        (P2-1 — added Nat column between Age and WC):
          Name (220px, hyperlink) | Age (50px) | Nat (50px) |
          WC (60px) | Stage (140px) | Form (120px) | Record (80px)

        The widget lives inside a CTkFrame "table_card" that matches
        the Dashboard's card aesthetic.
        """
        theme = get_theme()

        # Container card — gives the FighterTable a framed surface.
        table_card = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        table_card.pack(side="top", fill="both", expand=True,
                        padx=20, pady=(0, 10))

        # Build the column configs. P2-1: inserted the Nat column
        # between Age and WC so the layout is Name | Age | Nat | WC |
        # Stage | Form | Record (matches the column order specified
        # in the UI Implementation Plan v3).
        columns = [
            Column(NEW_COL_NAME, NEW_COLUMN_LABELS[NEW_COL_NAME],
                   NEW_COLUMN_WIDTHS[NEW_COL_NAME],
                   NEW_COLUMN_ANCHORS[NEW_COL_NAME], hyperlink=True),
            Column(NEW_COL_AGE, NEW_COLUMN_LABELS[NEW_COL_AGE],
                   NEW_COLUMN_WIDTHS[NEW_COL_AGE],
                   NEW_COLUMN_ANCHORS[NEW_COL_AGE]),
            Column(NEW_COL_NAT, NEW_COLUMN_LABELS[NEW_COL_NAT],
                   NEW_COLUMN_WIDTHS[NEW_COL_NAT],
                   NEW_COLUMN_ANCHORS[NEW_COL_NAT]),
            Column(NEW_COL_WC, NEW_COLUMN_LABELS[NEW_COL_WC],
                   NEW_COLUMN_WIDTHS[NEW_COL_WC],
                   NEW_COLUMN_ANCHORS[NEW_COL_WC]),
            Column(NEW_COL_STAGE, NEW_COLUMN_LABELS[NEW_COL_STAGE],
                   NEW_COLUMN_WIDTHS[NEW_COL_STAGE],
                   NEW_COLUMN_ANCHORS[NEW_COL_STAGE]),
            Column(NEW_COL_FORM, NEW_COLUMN_LABELS[NEW_COL_FORM],
                   NEW_COLUMN_WIDTHS[NEW_COL_FORM],
                   NEW_COLUMN_ANCHORS[NEW_COL_FORM]),
            Column(NEW_COL_RECORD, NEW_COLUMN_LABELS[NEW_COL_RECORD],
                   NEW_COLUMN_WIDTHS[NEW_COL_RECORD],
                   NEW_COLUMN_ANCHORS[NEW_COL_RECORD]),
            Column(NEW_COL_GYM, NEW_COLUMN_LABELS[NEW_COL_GYM],
                   NEW_COLUMN_WIDTHS[NEW_COL_GYM],
                   NEW_COLUMN_ANCHORS[NEW_COL_GYM]),
        ]

        # The FighterTable widget itself.
        self._fighter_table = FighterTable(
            table_card,
            columns=columns,
            on_row_click=self._on_row_click_new,
            on_row_double_click=self._on_row_double_click_new,
            on_sort_click=self._on_sort_click_new,
            page_size=PAGE_SIZE,
            empty_message="Your roster is empty.",
            fg_color=theme.colors.bg_surface, corner_radius=0,
        )
        self._fighter_table.pack(side="top", fill="both", expand=True,
                                  padx=1, pady=1)

        # Apply the initial sort indicator (default: insertion order,
        # no indicator shown — the FighterTable's set_sort_state is
        # called by _on_sort_click_new on the first header click).

    # ============================================================
    # SECTION 4 — PAGINATION (Prev / Next + page indicator)
    # ============================================================

    def _build_pagination(self):
        """Build the pagination bar.

        Layout:
          [← Prev]  Page 1 of 50  [Next →]

        The page indicator updates on every _refresh() to reflect the
        current page + total page count. Prev/Next are disabled when
        on the first/last page respectively.
        """
        theme = get_theme()

        pagination_row = ctk.CTkFrame(self, fg_color="transparent")
        pagination_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Prev button
        self._prev_button = ctk.CTkButton(
            pagination_row, text="← Prev",
            font=theme.fonts.body,
            width=80, height=28,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_prev_page,
        )
        self._prev_button.pack(side="left")

        # Page indicator — populated by _refresh
        self._pagination_label = ctk.CTkLabel(
            pagination_row, text="Page 1 of 1",
            font=theme.fonts.body,
            text_color=theme.colors.text_secondary,
        )
        self._pagination_label.pack(side="left", padx=20)

        # Next button
        self._next_button = ctk.CTkButton(
            pagination_row, text="Next →",
            font=theme.fonts.body,
            width=80, height=28,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_next_page,
        )
        self._next_button.pack(side="left")

    # ============================================================
    # SECTION 5 — VIEW PROFILE BUTTON (UI-POLISH Fix 3)
    # ============================================================

    def _build_view_profile_button(self):
        """Build the "View Profile" button below the pagination bar.

        Per UI-POLISH Fix 3: the user didn't discover that double-
        click navigates to Fighter Profile. The fix adds:
          1. Single-click on a row selects it (existing behavior).
          2. A visible "View Profile" button below the table that
             navigates to the selected fighter's profile.
        This makes the click-to-view affordance OBVIOUS — the player
        doesn't need to know about double-click.

        UI Implementation Plan v3 — P2-1: removed the redundant hint
        label that used to sit next to the button (it duplicated the
        footer hint below). The footer now carries the single hint:
        "single-click selects, double-click opens". One hint, not two.
        """
        theme = get_theme()
        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(side="top", fill="x", padx=20, pady=(0, 8))

        self._view_profile_button = ctk.CTkButton(
            button_row, text="▶  View Profile",
            font=theme.fonts.body,
            width=160, height=32,
            corner_radius=6,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            state="disabled",  # enabled when a row is selected
            command=self._on_view_profile_clicked,
        )
        self._view_profile_button.pack(side="left")

    # ============================================================
    # SECTION 6 — FOOTER (click-to-view-profile hint)
    # ============================================================

    def _build_footer(self):
        """Build the footer hint: 'Click a fighter to view profile'."""
        theme = get_theme()

        footer_label = ctk.CTkLabel(
            self,
            text="Click a fighter to view their profile — single-click selects, "
                 "double-click opens.",
            font=theme.fonts.caption,
            text_color=theme.colors.text_tertiary,
            anchor="w",
        )
        footer_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # HANDLERS — filter, search, sort, pagination, navigation
    # ============================================================

    def _on_weight_class_change(self, choice):
        """Handle weight-class dropdown change.

        Resets to page 1 (D3 — page state resets when filter changes)
        + triggers _refresh.
        """
        if choice == "All Weight Classes":
            self._weight_class_filter = None
        else:
            # Extract the weight_class_id from the dropdown value.
            # _refresh populates the dropdown with "WC Name (id=N)"
            # format so we can parse the id back out.
            try:
                # Find "id=N" in the choice string
                import re
                m = re.search(r"id=(\d+)", choice)
                if m:
                    self._weight_class_filter = int(m.group(1))
                else:
                    self._weight_class_filter = None
            except (ValueError, AttributeError):
                self._weight_class_filter = None
        self._current_page = 1
        self._refresh()

    def _on_gender_change(self, choice):
        """Handle gender dropdown change (UI-POLISH Fix 2).

        Maps the dropdown label to the fighters.gender column value:
          "All"     → None (no filter)
          "Male"    → "male"
          "Female"  → "female"
        Resets to page 1 + triggers _refresh.
        """
        if choice == "Male":
            self._gender_filter = "male"
        elif choice == "Female":
            self._gender_filter = "female"
        else:
            self._gender_filter = None
        self._current_page = 1
        self._refresh()

    @debounce(200)
    def _on_search_change(self, event=None):
        """Handle search-entry keystroke.

        Reads the current entry value + triggers _refresh. Page resets
        to 1 (D3 — page state resets when search changes).

        Phase 4 — Performance: @debounce(200) collapses fast typing
        into a single refresh. Without debounce, each keystroke
        re-queries the DB (4450 rows) + rebuilds 120 widgets (20
        rows × 6 cells × bindings). With 200ms debounce, a player
        typing "johnson" (7 keystrokes in ~1s) triggers ONE refresh
        instead of 7. The decorator uses self.after(ms, ...) so it
        integrates with Tk's event loop — no threads, no race
        conditions.
        """
        try:
            term = self._search_entry.get().strip()
        except Exception:
            term = ""
        # Only refresh if the term actually changed — avoids redundant
        # re-renders when the user presses arrow keys etc.
        if term != self._search_term:
            self._search_term = term
            self._current_page = 1
            self._refresh()

    def _on_prev_page(self):
        """Handle Prev button — go to previous page."""
        if self._current_page > 1:
            self._current_page -= 1
            self._refresh()

    def _on_next_page(self):
        """Handle Next button — go to next page."""
        total_pages = self._total_pages()
        if self._current_page < total_pages:
            self._current_page += 1
            self._refresh()

    def _on_view_profile_clicked(self):
        """Handle View Profile button click (UI-POLISH Fix 3).

        Navigates to the Fighter Profile screen for the currently
        selected row. Defensive: if no row is selected, no-op (the
        button should be disabled in that case, but defensive).
        """
        # UI Fix Plan 2 — Phase 3, Fix 11: when using FighterTable,
        # the selected fighter_id comes from the widget, not the
        # Treeview. _navigate_to_selected_profile handles both.
        self._navigate_to_selected_profile()

    # ============================================================
    # UI Fix Plan 2 — Phase 3, Fix 11: FighterTable handlers.
    # ============================================================

    def _on_sort_click_new(self, column_id, reverse):
        """Handle sort header click from the FighterTable.

        Maps the new column ids (NEW_COL_NAME, NEW_COL_AGE, etc.)
        to the underlying sort_column value used by _sort_roster.
        Then triggers _refresh which re-sorts + re-renders.
        """
        # Map FighterTable column id → self._sort_column value.
        # We reuse the existing _sort_roster logic by translating
        # the new column ids to the old ones where possible + adding
        # new ones (age) for the new path.
        col_map = {
            NEW_COL_NAME: "fighter_id",  # name sort falls back to id
            NEW_COL_AGE: "age",
            NEW_COL_NAT: "nation_name",
            NEW_COL_WC: COL_WC,
            NEW_COL_STAGE: COL_PHASE,
            NEW_COL_FORM: COL_MOMENTUM,
            NEW_COL_RECORD: COL_RECORD,
        }
        new_sort = col_map.get(column_id, "fighter_id")
        if self._sort_column == new_sort:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = new_sort
            self._sort_reverse = reverse
        # The FighterTable already updated its sort indicator via
        # set_sort_state (called internally before on_sort_click).
        self._refresh()

    def _on_row_click_new(self, fighter_id):
        """Handle single-click on a FighterTable row.

        Enables the View Profile button so the player can navigate
        via the button (Fix 13 also makes the fighter name a
        hyperlink — that fires its own navigation independently).
        """
        try:
            if fighter_id is not None:
                self._view_profile_button.configure(state="normal")
            else:
                self._view_profile_button.configure(state="disabled")
        except Exception:
            pass

    def _on_row_double_click_new(self, fighter_id):
        """Handle double-click on a FighterTable row — navigate to profile.

        Per Fix 13: the fighter name is already a hyperlink that
        navigates on single-click. Double-click anywhere in the row
        ALSO navigates (covers players who don't realize the name is
        a link).
        """
        if fighter_id is None:
            return
        try:
            state = get_state()
            profile_screen = state.get_screen("fighter_profile")
            if profile_screen is not None and hasattr(
                    profile_screen, "set_fighter_id"):
                profile_screen.set_fighter_id(fighter_id)
            state.set_active_screen("fighter_profile")
        except ValueError as e:
            print(f"Warning: navigation to fighter_profile failed: {e}",
                  flush=True)
        except Exception as e:
            print(f"Warning: navigation handler failed: {e}", flush=True)

    def _navigate_to_selected_profile(self):
        """Shared navigation helper — used by View Profile button.

        UI Implementation Plan v3 — P2-3: the Treeview fallback path
        was deleted (USE_TREEVIEW flag gone). The FighterTable is the
        only table implementation; the selected fighter_id is read
        directly from the widget.
        """
        if self._fighter_table is None:
            return
        fighter_id = self._fighter_table.get_selected_fighter_id()
        if fighter_id is None:
            return
        try:
            state = get_state()
            profile_screen = state.get_screen("fighter_profile")
            if profile_screen is not None and hasattr(
                    profile_screen, "set_fighter_id"):
                profile_screen.set_fighter_id(fighter_id)
            state.set_active_screen("fighter_profile")
        except ValueError as e:
            print(f"Warning: navigation to fighter_profile failed: {e}",
                  flush=True)
        except Exception as e:
            print(f"Warning: navigation handler failed: {e}", flush=True)

    # ============================================================
    # REFRESH CALLBACK (registered with GameState)
    # ============================================================

    def _refresh(self):
        """Refresh callback — re-query + re-render.

        Registered with GameState as this screen's refresh callback.
        Called:
          - Once on init (via after(50, ...)).
          - On every navigation to this screen (set_active_screen
            triggers state.refresh(name)).
          - On refresh_all() (after Advance Day, Save, Load, theme
            toggle).

        Safe to call repeatedly — clears old Treeview rows, re-queries,
        re-renders. Defensive against DB errors.
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                return
            promo_id = state.get_player_promotion_id()

            # UI Fix Plan 2 — Phase 3, Fix 11b: cache the sim date
            # string for age computation in _render_table_new. Read
            # once per refresh — used for every row's Age column.
            self._sim_date_str = self._read_sim_date(conn)

            # Populate the weight-class dropdown (D4). Done on every
            # refresh so newly-signed/cut fighters' weight classes
            # appear/disappear.
            self._refresh_weight_class_dropdown(conn, promo_id)

            # Query the roster (filtered + searched).
            self._roster_data = self._query_roster(conn, promo_id)

            # Sort the roster (D8).
            self._sort_roster()

            # Clamp the current page to the last valid page (D10).
            total_pages = self._total_pages()
            if self._current_page > total_pages:
                self._current_page = max(1, total_pages)

            # Render the current page of rows.
            # P2-3: the legacy Treeview render path was deleted —
            # FighterTable.set_rows is the only render call.
            self._render_table_new()
            self._refresh_pagination(total_pages)
            self._refresh_subtitle(conn, promo_id, len(self._roster_data))

            # After a re-render, the selection is gone — disable the
            # View Profile button until the player picks a new row
            # (UI-POLISH Fix 3).
            try:
                if self._view_profile_button:
                    self._view_profile_button.configure(state="disabled")
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: RosterScreen._refresh failed: {e}", flush=True)

    def _read_sim_date(self, conn):
        """Read the current sim date from simulation_clock.

        Used for age computation in _render_table_new. Defensive —
        returns None on any query failure (the Age column will show
        blank for all rows, not a crash).
        """
        try:
            row = conn.execute(
                "SELECT current_date FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            pass
        return None

    # ------------------------------------------------------------
    # Subtitle — "Promotion Name (N,NNN fighters)"
    # ------------------------------------------------------------

    def _refresh_subtitle(self, conn, promo_id, total_count):
        """Update the subtitle label with promotion name + count.

        UI Fix Plan 2 — Phase 3, Fix 9: also loads the promotion
        logo into self._promo_logo_label (60x60 PNG from
        src/ui/assets/promo_logos/). Falls back to text initials
        if the logo isn't found or PIL isn't available.
        """
        try:
            theme = get_theme()
            promo_name = "Your Promotion"
            try:
                promo_row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id=?",
                    (promo_id,),
                ).fetchone()
                if promo_row and promo_row[0]:
                    promo_name = promo_row[0]
            except sqlite3.Error:
                pass

            text = f"{promo_name}  ·  {total_count:,} fighters"
            self._subtitle_label.configure(
                text=text,
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )

            # ---- Promotion logo (Fix 9) ----
            self._cached_promo_name = promo_name
            self._refresh_promo_logo(promo_id, promo_name)
        except Exception as e:
            print(f"Warning: roster subtitle refresh failed: {e}",
                  flush=True)

    def _refresh_promo_logo(self, promo_id, promo_name):
        """Load the promotion logo into the header logo label (Fix 9).

        Tries _load_promo_logo (PIL image resize). On success, wraps
        in CTkImage + sets on self._promo_logo_label. On failure,
        shows the promotion's initials (first letter of each word in
        promo_name, up to 3 chars) as a text fallback.
        """
        try:
            theme = get_theme()
            pil_img = _load_promo_logo(promo_id, promo_name, size=60)
            if pil_img is not None:
                self._promo_logo_ctk_image = ctk.CTkImage(
                    light_image=pil_img, dark_image=pil_img,
                    size=(60, 60),
                )
                self._promo_logo_label.configure(
                    image=self._promo_logo_ctk_image, text="")
            else:
                # Text-initials fallback.
                initials = self._promo_initials(promo_name)
                self._promo_logo_label.configure(
                    image=None, text=initials,
                    font=(theme.fonts.h2[0], 22, "bold"),
                    text_color=theme.colors.gold,
                )
        except Exception as e:
            print(f"Warning: promo logo refresh failed: {e}", flush=True)

    @staticmethod
    def _promo_initials(promo_name):
        """Compute up to 3-letter initials from a promotion name.

        "Alpha Combat Federation" → "ACF". "Rival Fight League" →
        "RFL". Defensive — returns "?" if the name is empty.
        """
        if not promo_name:
            return "?"
        words = str(promo_name).strip().split()
        if not words:
            return "?"
        initials = "".join(w[0].upper() for w in words if w)[:3]
        return initials or "?"

    # ------------------------------------------------------------
    # Weight-class dropdown
    # ------------------------------------------------------------

    def _refresh_weight_class_dropdown(self, conn, promo_id):
        """Populate the weight-class dropdown with the player's roster
        weight classes.

        Per D4: lists every weight class present in the player's
        promotion + "All Weight Classes" as the first option. Values
        are formatted as "WC Name (gender) [id=N]" so we can extract
        the id when the player selects one.

        Per UI-POLISH Fix 2: when a gender filter is active, the
        dropdown only shows weight classes for that gender — saves
        the player from picking a mismatched combination (e.g., Female
        + Heavyweight) that would yield an empty result set.

        Defensive — if the query fails, the dropdown just shows "All
        Weight Classes" (the player can still see the full roster).
        """
        try:
            # Get the current dropdown value so we can preserve it
            # across refreshes (otherwise the dropdown resets to
            # "All Weight Classes" on every refresh — annoying).
            current_value = None
            try:
                current_value = self._weight_class_menu.get()
            except Exception:
                pass

            # Query weight classes present in the player's roster.
            # If a gender filter is active, filter by gender too.
            rows = []
            try:
                if self._gender_filter is not None:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT wc.weight_class_id, wc.name, wc.gender
                        FROM fighters f
                        JOIN weight_classes wc
                          ON wc.weight_class_id = f.weight_class_id
                        WHERE f.current_promotion_id = ?
                          AND f.is_active = 1
                          AND f.gender = ?
                        ORDER BY wc.display_order ASC, wc.name ASC
                        """,
                        (promo_id, self._gender_filter),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT wc.weight_class_id, wc.name, wc.gender
                        FROM fighters f
                        JOIN weight_classes wc
                          ON wc.weight_class_id = f.weight_class_id
                        WHERE f.current_promotion_id = ? AND f.is_active = 1
                        ORDER BY wc.display_order ASC, wc.name ASC
                        """,
                        (promo_id,),
                    ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: weight-class query failed: {e}",
                      flush=True)

            # Build the dropdown values. "All Weight Classes" first.
            values = ["All Weight Classes"]
            for wc_id, wc_name, wc_gender in rows:
                gender_tag = f" ({wc_gender})" if wc_gender else ""
                values.append(f"{wc_name}{gender_tag} [id={wc_id}]")

            # Update the dropdown values without losing the current
            # selection (if it's still valid).
            self._weight_class_menu.configure(values=values)

            # If the current value is no longer in the list (e.g., the
            # last fighter in that weight class was cut, OR the gender
            # filter narrowed the list), reset to "All Weight Classes".
            if current_value and current_value in values:
                self._weight_class_menu.set(current_value)
            else:
                self._weight_class_menu.set("All Weight Classes")
                self._weight_class_filter = None
        except Exception as e:
            print(f"Warning: weight-class dropdown refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Query the roster (filtered + searched)
    # ------------------------------------------------------------

    def _query_roster(self, conn, promo_id):
        """Query the roster with the current filter + search applied.

        Per D1: reads from fighters + fighter_descriptors (cache) +
        fighter_career (career stats only) + weight_classes (game
        state). NEVER reads from fighter_attributes /
        fighter_personality / fighter_bios / fighter_contracts.

        Returns:
            List of dicts, one per fighter. Each dict has keys:
                fighter_id, name, weight_class_name, career_phase_stored,
                momentum_stored, narrative_stored, record_wins,
                record_losses, record_draws.
            The "_stored" values are the raw "label||phrase" cache
            values — decode_phrase() is applied at render time so
            sorting can use the canonical label if needed (D8).
        """
        rows = []
        try:
            # Build the WHERE clause. The filter + search are dynamic.
            where_clauses = [
                "f.current_promotion_id = ?",
                "f.is_active = 1",
            ]
            params = [promo_id]

            if self._weight_class_filter is not None:
                where_clauses.append("f.weight_class_id = ?")
                params.append(self._weight_class_filter)

            # Per UI-POLISH Fix 2: gender filter. Applied in SQL —
            # efficient even with 1000+ rows.
            if self._gender_filter is not None:
                where_clauses.append("f.gender = ?")
                params.append(self._gender_filter)

            if self._search_term:
                # Case-insensitive substring on first_name + last_name
                # + nickname. SQLite's LIKE is case-insensitive for
                # ASCII by default. The %term% pattern matches any
                # occurrence. We search all three name fields via OR.
                like_term = f"%{self._search_term}%"
                where_clauses.append(
                    "(f.first_name LIKE ? OR f.last_name LIKE ? "
                    "OR f.nickname LIKE ?)"
                )
                params.extend([like_term, like_term, like_term])

            where_sql = " AND ".join(where_clauses)

            # JOIN: fighters + fighter_descriptors (LEFT JOIN —
            # defensive, in case a fighter has no descriptor row yet)
            # + fighter_career (LEFT JOIN — same defensiveness) +
            # weight_classes (LEFT JOIN — for the WC name).
            #
            # Per §17.3, fighters / fighter_career / weight_classes
            # are simulation tables (the interpretation layer never
            # writes to them). The Roster reads ONLY from:
            #   - fighters: first_name, last_name, nickname,
            #     weight_class_id (game state — names + classification,
            #     NOT attribute values per §14)
            #   - fighter_descriptors: career_phase, momentum,
            #     narrative_family voice phrases (cache — §17.3 cache
            #     table)
            #   - fighter_career: record_wins, record_losses,
            #     record_draws (career stats — explicitly OK per §14)
            #   - weight_classes: name (game state)
            #
            # NEVER reads from fighter_attributes / fighter_personality
            # (raw 0-100 values, §14-protected).
            sql = f"""
                SELECT f.fighter_id, f.first_name, f.last_name, f.nickname,
                       f.date_of_birth,
                       wc.name AS weight_class_name,
                       n.name AS nation_name,
                       g.name AS gym_name,
                       fd.career_phase, fd.momentum, fd.narrative_family,
                       fc.record_wins, fc.record_losses, fc.record_draws
                FROM fighters f
                LEFT JOIN weight_classes wc
                  ON wc.weight_class_id = f.weight_class_id
                LEFT JOIN nations n
                  ON n.nation_id = f.birth_nation_id
                LEFT JOIN gyms g
                  ON g.gym_id = f.current_gym_id
                LEFT JOIN fighter_descriptors fd
                  ON fd.fighter_id = f.fighter_id
                LEFT JOIN fighter_career fc
                  ON fc.fighter_id = f.fighter_id
                WHERE {where_sql}
                ORDER BY f.fighter_id ASC
            """
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: roster query failed: {e}", flush=True)
            return []

        # Build the roster data list.
        # UI Fix Plan 2 — Phase 3, Fix 11b: also store date_of_birth
        # so _render_table_new can compute the Age column.
        # UI Implementation Plan v3 — P2-1: also store nation_name
        # so _render_table_new can abbreviate it to the Nat column.
        roster = []
        for r in rows:
            (fid, first, last, nick, dob, wc_name, nation_name,
             gym_name, phase_stored, mom_stored, narr_stored, wins,
             losses, draws) = r
            roster.append({
                "fighter_id": fid,
                "first_name": first,
                "last_name": last,
                "name": _format_name(first, last, nick),
                "name_short": _format_name_short(first, last),
                "date_of_birth": dob,
                "weight_class_name": wc_name or "Unknown",
                "nation_name": nation_name or "",
                "gym_name": gym_name or "",
                "career_phase_stored": phase_stored,
                "momentum_stored": mom_stored,
                "narrative_stored": narr_stored,
                "record_wins": wins,
                "record_losses": losses,
                "record_draws": draws,
            })
        return roster

    # ------------------------------------------------------------
    # Sort the roster (D8)
    # ------------------------------------------------------------

    def _sort_roster(self):
        """Sort self._roster_data by self._sort_column.

        Per D8: sort is applied in Python (not SQL) because the voice
        phrases need decode_phrase() before sorting — sorting raw
        "label||phrase" strings would sort by the canonical label, not
        the player-facing phrase, which is unintuitive.

        Sort keys:
          - fighter_id (default) → int, ascending
          - name → string, case-insensitive
          - age → int (computed from DOB + sim date), ascending
          - weight_class_name → string, case-insensitive
          - career_phase → decoded phrase (or "" if None)
          - momentum → decoded phrase (or "" if None)
          - record → total fights (wins + losses + draws)
          - narrative → decoded phrase (or "" if None)

        UI Fix Plan 2 — Phase 3, Fix 11b: added the "age" sort key for
        the new FighterTable's Age column. The age is computed from
        date_of_birth + the cached sim date (self._sim_date_str).
        """
        col = self._sort_column
        reverse = self._sort_reverse

        def sort_key(item):
            if col == "fighter_id":
                return item["fighter_id"]
            if col == "age":
                # UI Fix Plan 2 — Phase 3, Fix 11b: sort by computed
                # age. Defensive — fighters with bad DOB get age 0
                # (sorts first ascending, last descending).
                age_str = _compute_age_from_dob(
                    item.get("date_of_birth"), self._sim_date_str)
                try:
                    return int(age_str) if age_str else 0
                except (TypeError, ValueError):
                    return 0
            if col == COL_WC:
                return item["weight_class_name"].lower()
            if col == "nation_name":
                # P2-1: sort by nation name. Falls back to "" so
                # fighters with NULL birth_nation_id sort consistently.
                return (item.get("nation_name") or "").lower()
            if col == COL_PHASE:
                return _phrase_or_fallback(
                    item["career_phase_stored"], "") or ""
            if col == COL_MOMENTUM:
                return _phrase_or_fallback(
                    item["momentum_stored"], "") or ""
            if col == COL_RECORD:
                # Sort by total fights — most-experienced first by
                # default (reverse=True makes it desc, but we want
                # asc on first click, so use negative total).
                total = (item["record_wins"] or 0) + \
                        (item["record_losses"] or 0) + \
                        (item["record_draws"] or 0)
                return total
            return 0

        try:
            self._roster_data.sort(key=sort_key, reverse=reverse)
        except (TypeError, ValueError) as e:
            # Defensive — if a sort key has mixed types, fall back to
            # fighter_id sort.
            print(f"Warning: roster sort failed, falling back: {e}",
                  flush=True)
            self._roster_data.sort(key=lambda x: x["fighter_id"])

    # ------------------------------------------------------------
    # Render the table (current page of rows)
    # ------------------------------------------------------------

    def _render_table_new(self):
        """Render the current page of rows into the FighterTable.

        UI Fix Plan 2 — Phase 3, Fix 11 (AD-5): the new path. Builds
        a list of row dicts (one per fighter on the current page) +
        passes them to FighterTable.set_rows. The widget handles the
        actual widget creation (HyperlinkLabel for the Name column,
        plain CTkLabel for the others).

        Per Fix 11b: computes Age from date_of_birth + sim date.
        Per Fix 11c: uses short Stage/Form phrases (not the long-form
        decoded voice phrases the Treeview used).
        Per Fix 13: the Name column is a HyperlinkLabel (handled by
        the FighterTable via the Column(hyperlink=True) config).

        Per D6: empty-state handling — if no rows match the current
        filter/search, pass an empty list + the appropriate empty
        message to set_rows.
        """
        try:
            if self._fighter_table is None:
                return

            # Compute the page slice.
            start = (self._current_page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_rows = self._roster_data[start:end]

            if not page_rows:
                # Empty state (D6). Pass an empty list + the
                # appropriate empty message based on WHY the roster
                # is empty.
                empty_msg = self._empty_state_message()
                self._fighter_table.set_rows([], empty_message=empty_msg)
                return

            # Build the row dicts for the FighterTable.
            rows = []
            for fighter in page_rows:
                # Per Fix 11b: compute age from DOB + sim date.
                age_str = _compute_age_from_dob(
                    fighter.get("date_of_birth"), self._sim_date_str)
                # Per Fix 11b: abbreviate weight class.
                wc_abbr = _abbreviate_wc(fighter["weight_class_name"])
                # Per P2-1: abbreviate nationality to 3-letter code.
                nat_abbr = _abbreviate_nat(fighter["nation_name"])
                # Per Fix 11c: short Stage + Form phrases.
                stage_phrase = _stage_short_phrase(
                    fighter["career_phase_stored"])
                form_phrase = _form_short_phrase(
                    fighter["momentum_stored"])
                record_str = _format_record(
                    fighter["record_wins"],
                    fighter["record_losses"],
                    fighter["record_draws"],
                )
                rows.append({
                    "fighter_id": fighter["fighter_id"],
                    NEW_COL_NAME: fighter["name_short"],
                    NEW_COL_AGE: age_str,
                    NEW_COL_NAT: nat_abbr,
                    NEW_COL_WC: wc_abbr,
                    NEW_COL_STAGE: stage_phrase,
                    NEW_COL_FORM: form_phrase,
                    NEW_COL_RECORD: record_str,
                    NEW_COL_GYM: fighter.get("gym_name") or "—",
                })

            self._fighter_table.set_rows(rows)
        except Exception as e:
            print(f"Warning: roster table render (new) failed: {e}",
                  flush=True)

    def _empty_state_message(self):
        """Return the appropriate empty-state message (D6).

        - No fighters in roster at all → "Your roster is empty. Sign
          some free agents to build your stable."
        - Filter excludes everyone → "No fighters match this weight
          class."
        - Search excludes everyone → "No fighters match '<term>'. Try
          a different name."
        """
        # If the underlying roster (no filter, no search) is also
        # empty, the player has no fighters at all.
        try:
            state = get_state()
            conn = state.get_conn()
            promo_id = state.get_player_promotion_id()
            total = conn.execute(
                "SELECT COUNT(*) FROM fighters "
                "WHERE current_promotion_id=? AND is_active=1",
                (promo_id,),
            ).fetchone()[0]
        except Exception:
            total = 0

        if total == 0:
            return "Your roster is empty. Sign some free agents to build your stable."
        if self._search_term:
            return f"No fighters match '{self._search_term}'. Try a different name."
        if self._weight_class_filter is not None:
            return "No fighters match this weight class."
        return "No fighters match the current view."

    # ------------------------------------------------------------
    # Pagination label
    # ------------------------------------------------------------

    def _refresh_pagination(self, total_pages):
        """Update the pagination label + Prev/Next button states."""
        try:
            theme = get_theme()
            if total_pages == 0:
                self._pagination_label.configure(
                    text="No results",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                )
                self._prev_button.configure(state="disabled")
                self._next_button.configure(state="disabled")
                return

            self._pagination_label.configure(
                text=f"Page {self._current_page} of {total_pages}",
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )

            # Disable Prev on page 1, Next on last page.
            self._prev_button.configure(
                state="normal" if self._current_page > 1 else "disabled"
            )
            self._next_button.configure(
                state="normal" if self._current_page < total_pages else "disabled"
            )
        except Exception as e:
            print(f"Warning: pagination refresh failed: {e}", flush=True)

    def _total_pages(self):
        """Return the total number of pages based on the current roster."""
        total_fighters = len(self._roster_data)
        if total_fighters == 0:
            return 0
        return (total_fighters + PAGE_SIZE - 1) // PAGE_SIZE
