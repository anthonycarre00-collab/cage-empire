"""CAGE EMPIRE — Free Agents screen (Stage 6 — Task 6.5).

The Talent Hunter's pool — every unsigned fighter in the world
(current_promotion_id IS NULL + is_active=1 + is_retired=0).
Mirrors the Roster pattern (Task 6.4) — same Treeview table, same
filters, same pagination — with TWO differences:

  1. The WHERE clause flips: instead of `current_promotion_id = ?`
     it's `current_promotion_id IS NULL`. These fighters belong to
     NO promotion — they're free to sign with anyone.
  2. A "Sign Selected Fighter" button below the table calls
     `services.contracts.sign_free_agent(conn, fighter_id,
     promotion_id, start_date)` which writes a new contract row +
     flips the fighter's current_promotion_id to the player's
     promotion + writes a signing news item + publishes
     Events.FIGHTER_SIGNED on the event bus.

Per docs/GUI_PLAN.md §5.2 (FIGHTERS group):
  "Free Agents — Unsigned fighters available to sign. Primary
  tables: fighters (where current_promotion_id IS NULL),
  scouting_reports."

Per docs/CONVENTIONS.md §17 (UI Snapshot Rule — CRITICAL):
  Office Mode UI screens MUST read from `*_descriptors` cache
  tables for fighter interpretation data. The Free Agents screen
  reads from:
    - `fighters` (game state — first_name, last_name, nickname,
      weight_class_id, current_promotion_id, is_active,
      is_retired. Names + classification are NOT raw attribute
      values per §14.)
    - `fighter_descriptors` (cache — career_phase, momentum,
      potential_desc voice phrases per §17.3. The interpretation
      layer is the only writer.)
    - `fighter_career` (game state — record_wins, record_losses,
      record_draws. Career stats are OK per §14 ("career stats not
      attributes").)
    - `weight_classes` (game state — weight class name.)

  This screen NEVER reads from `fighter_attributes` (raw 0-100
  values), `fighter_personality` (raw trait values), `fighter_bios`
  (long-form prose — that's for Fighter Profile), `fighter_contracts`
  (simulation table per §17.3). See D1.

Per docs/CONVENTIONS.md §14 (Interpretation Layer — CRITICAL):
  No raw attribute values appear in the player-facing UI.
    - Career phase → decoded voice phrase ("a blue-chip prospect
      early in his career") — never the raw "prospect" label.
    - Momentum → decoded voice phrase ("riding a hot streak") —
      never the raw "high" label.
    - Potential → decoded voice phrase from `potential_desc`. The
      raw 0-100 potential number lives in `fighter_career.potential`
      and is §14-protected. `potential_desc` is the interpretation-
      layer projection of that number. As of schema 3.12.0 this
      column is NULL across the seeded DB (the interpretation layer
      has not yet been extended to populate it) — the screen shows
      "(no scouting report yet)" as a sensible fallback. This is the
      SAME information asymmetry WMMA5 + EWMMA use: the player
      cannot see a free agent's potential until they scout them.
      Per the Soul doc, this is correct behavior, not a regression.
    - Record → "18-5-0" — OK per §14 (career stats, not attributes).

Per docs/CONVENTIONS.md §17.4 ("Rich Not Thin" — CRITICAL):
  Every cache label has an associated voice phrase. The cache stores
  "label||phrase"; the UI shows the phrase. The Free Agents screen
  uses `interpretation.context_engine.decode_phrase` (single source
  of truth) to extract the phrase.

Architecture (mirrors RosterScreen — same pattern all Office Mode
table-based screens follow):
  - FreeAgentsScreen(ctk.CTkFrame) — the screen widget.
  - _build_header() — H1 title + free-agent-count subtitle.
  - _build_filter_row() — weight-class dropdown + name search entry.
  - _build_table() — ttk.Treeview with 6 columns (Name, WC, Career
    Phase, Potential, Record, Momentum). Themed to match the
    Office dark palette via a custom ttk.Style.
  - _build_pagination() — Prev / Next buttons + page indicator.
  - _build_sign_bar() — "Sign Selected Fighter" + status label.
  - _refresh() — registered with GameState; re-queries the free
    agents (filtered + searched + paginated) + re-renders the
    Treeview. Safe to call repeatedly (clears old rows first).

Navigation:
  - Double-click a row → set_fighter_id(fighter_id) on the Fighter
    Profile screen → state.set_active_screen("fighter_profile").
  - Single-click selects a row (the highlight the player expects)
    + enables the "Sign Selected Fighter" button.

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Source-of-truth map. See the §17 comment block above. The
      rule: fighter INTERPRETATION data (career_phase, momentum,
      potential_desc) comes from fighter_descriptors cache ONLY.
      Fighter NAMES + weight_class_id come from `fighters` (game
      state). Record comes from `fighter_career` (career stats —
      OK per §14). Weight class name from `weight_classes` (game
      state). The Free Agents screen NEVER touches
      fighter_attributes / fighter_personality / fighter_bios /
      fighter_contracts.

      Note on potential_desc: §14 protects the raw 0-100 potential
      number in fighter_career.potential. The interpretation layer
      projects that to fighter_descriptors.potential_desc as a
      voice phrase. As of schema 3.12.0, the daily interpretation
      pass has not yet been extended to populate potential_desc —
      it is NULL across the seeded DB. The screen reads from
      potential_desc anyway (per the brief) and falls back to a
      sensible voice phrase ("no scouting report yet") on NULL.
      When the interpretation layer is extended to populate
      potential_desc, the screen will automatically pick up the
      voice phrase — no code change needed. This is the correct
      forward-compatible behavior.

  D2  "Sign Selected Fighter" button (below the table, NOT per-row
      buttons). The brief shows "[Sign Fighter] button on each row"
      in the mockup, but ttk.Treeview doesn't natively support per-
      row buttons — embedding them requires a custom cell renderer
      or a parallel widget overlay, both of which break the
      Roster's shared pattern (D2 in roster.py: "ttk.Treeview via
      tkinter.ttk, not ttkbootstrap"). The cleaner, consistent
      approach is a single "Sign Selected Fighter" button below the
      table that signs the currently-selected row. Single-click
      selects (Treeview default); the Sign button reads
      `self._treeview.selection()[0]` to recover the fighter_id
      (stored as the item iid, same pattern as the Roster's
      double-click handler). This matches how WMMA5 + EWMMA do it:
      one action button, the player picks the row first.

      The button is gold-themed (matches the top-bar Advance Day
      button — the other dopamine button in the app). Disabled
      when no row is selected.

  D3  Sign flow. On click:
        1. Read the selected fighter_id from the Treeview selection.
        2. Read the current sim date from simulation_clock (used as
           the contract start_date).
        3. Call `services.contracts.sign_free_agent(conn,
           fighter_id, promotion_id, start_date, salary=50000.0)`.
           This is the Task 6.0-extracted helper that does the
           contract insert + promotion_id update + news item write
           + Events.FIGHTER_SIGNED publish.
        4. Commit the conn (the helper doesn't commit — caller's
           responsibility per its docstring).
        5. Show a status message: success ("Signed Hiroki Nakamura
           to Alpha Combat Federation.") or failure ("Could not
           sign — fighter may have retired or signed elsewhere.").
        6. Call state.refresh_all() so the Roster + Dashboard pick
           up the new signing immediately.
        7. Call self._refresh() to update the Free Agents table
           (the signed fighter no longer appears in the list).

      The salary defaults to 50000.0 (matches the seed default —
      no negotiation flow yet, that's a future task per the
      sign_free_agent docstring).

  D4  Status feedback. A small label below the Sign button shows
      the last action's result. Color-coded: gold for success,
      crimson for failure, text_tertiary for idle. Mirrors the
      Dashboard's event-card accent system.

  D5  Weight-class dropdown. Same pattern as the Roster — lists
      every weight class present in the FREE AGENT pool (not the
      player's roster). The dropdown is re-populated on every
      _refresh so newly-signed/cut fighters' weight classes appear
      or disappear.

  D6  Empty-state handling. Every state degrades gracefully:
      - No free agents at all → "No free agents available. Advance
        a few days — contracts expire and fighters become
        available."
      - No free agents match the filter → "No free agents match
        this weight class."
      - No free agents match the search → "No free agents match
        '<term>'. Try a different name."

  D7  Pagination. Same as the Roster — 20 rows per page, Prev /
      Next buttons, page indicator. Page state survives across
      _refresh() calls (stored in self._current_page) so navigating
      to Fighter Profile and back preserves the page the player was
      on. Page state resets to 1 when the filter or search changes.

  D8  Navigation. Double-click → Fighter Profile (same as the
      Roster). The fighter_id is stored as the Treeview item iid
      (string) — recovered via `int(self._treeview.selection()[0])`.

  D9  Treeview style. Same as the Roster — `FreeAgents.Treeview`
      style name (separate from `Roster.Treeview` so the two can be
      themed independently if a future task needs it). Re-applied
      on every _refresh() so theme-change refresh picks up new
      colors.

  D10 Sortable columns. Same as the Roster — heading clicks sort
      the underlying data by that column. Sort state tracked in
      self._sort_column + self._sort_reverse. Default sort is by
      fighter_id ascending.

  D11 Performance. The free-agent query is one JOIN across 4 tables
      (fighters + fighter_descriptors + fighter_career +
      weight_classes) with a WHERE clause on current_promotion_id
      IS NULL + is_active + is_retired. On the live 4450-fighter
      DB, this returns ~600 rows in <30ms (verified during pre-
      flight: 601 free agents). decode_phrase() calls are pure
      Python string splits. Treeview insert ~10ms for 20 rows.
      Well within the §17.5 spirit.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

# PIL is used for the promotion logo load + resize (mirrors the
# Roster's logo loader). Falls back gracefully if PIL isn't installed.
try:
    from PIL import Image as _PIL_Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from ui.theme import get_theme
from ui.state import get_state
from ui.voice_display import title_case_phrase, \
    display_attr_descriptor

# UI Implementation Plan v3 — P0-1: the new FighterTable widget
# replaces the ttk.Treeview (the legacy Treeview code was deleted in
# UI Implementation Plan v3 — P2-3, ~600 LOC of dead code removed).
# Mirrors the Roster's import pattern.
from ui.widgets.fighter_table import FighterTable, Column

# Phase 4 — Performance: debounce search entry (same pattern as Roster).
from ui.perf import debounce

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (mirrors
# DashboardScreen's D4 + RosterScreen's D4).
from interpretation.context_engine import decode_phrase


# ============================================================
# PROMOTION LOGO PATH (mirrors the Roster — P0-1 visual consistency)
# ============================================================
# Logos live at src/ui/assets/promo_logos/<promotion_id>_<slug>.png.
# The slug is the promotion name lowercased with underscores. We
# resolve the logo at refresh time by globbing for "<promo_id>_*.png"
# — robust against slug renames (same approach as the Roster).
_PROMO_LOGOS_DIR = (Path(__file__).resolve().parent.parent
                    / "assets" / "promo_logos")


# ============================================================
# CONSTANTS
# ============================================================

# Page size — matches the Roster (D3 in roster.py: "show 20 at a time").
PAGE_SIZE = 20

# Default salary for sign_free_agent (matches the seed default in
# sign_free_agent's docstring + the seed_data.py _seed_default_fighter_
# contract helper). No negotiation flow yet — that's a future task.
DEFAULT_SIGNING_SALARY = 50000.0

# Sort-column identifiers used by _sort_data + the FighterTable's
# on_sort_click callback. These were originally Treeview column IDs
# (UI Implementation Plan v3 — P0-1); the Treeview was deleted in
# P2-3, but the identifiers survive as the sort_column values the
# FighterTable path maps to. Mirrors roster.py's pattern.
COL_WC = "weight_class"
COL_PHASE = "career_phase"
COL_POTENTIAL = "potential"
COL_RECORD = "record"
COL_MOMENTUM = "momentum"


# ============================================================
# UI Implementation Plan v3 — P0-1: new column set for the
# FighterTable widget. Mirrors the Roster's NEW_COL_* layout + adds
# the "Ceiling" column (renamed from "Potential"). Column order:
#   Name | Age | WC | Stage | Ceiling | Form | Record
# Changes vs the legacy Treeview:
#   - "Career Phase" → "Stage" (short phrases, not long-form)
#   - "Potential" → "Ceiling" (short phrases; renamed per the plan)
#   - "Momentum" → "Form" (short phrases)
#   - Age added (computed from DOB + sim date, mirrors Roster)
#   - WC abbreviated (HW, LHW, MW, WW, LW, FW, BW, FlyW, etc.)
#   - Name column drops the nickname (first + last only)
# ============================================================
NEW_COL_NAME = "name"
NEW_COL_AGE = "age"
NEW_COL_WC = "wc"
NEW_COL_STAGE = "stage"
NEW_COL_CEILING = "ceiling"
NEW_COL_FORM = "form"
NEW_COL_RECORD = "record"

NEW_COLUMN_LABELS = {
    NEW_COL_NAME: "Name",
    NEW_COL_AGE: "Age",
    NEW_COL_WC: "WC",
    NEW_COL_STAGE: "Stage",
    NEW_COL_CEILING: "Ceiling",
    NEW_COL_FORM: "Form",
    NEW_COL_RECORD: "Record",
}

# Column widths rebalanced for the 7-column layout. Total ~720px —
# matches the Roster's table so the two sister screens read as a pair.
NEW_COLUMN_WIDTHS = {
    NEW_COL_NAME: 220,
    NEW_COL_AGE: 50,
    NEW_COL_WC: 60,
    NEW_COL_STAGE: 140,
    NEW_COL_CEILING: 130,
    NEW_COL_FORM: 120,
    NEW_COL_RECORD: 80,
}

NEW_COLUMN_ANCHORS = {
    NEW_COL_NAME: "w",
    NEW_COL_AGE: "center",
    NEW_COL_WC: "center",
    NEW_COL_STAGE: "w",
    NEW_COL_CEILING: "w",
    NEW_COL_FORM: "w",
    NEW_COL_RECORD: "center",
}


# ============================================================
# UI Implementation Plan v3 — P0-1: WC abbreviation map.
# Mirrors the Roster's _WC_ABBREVIATIONS — kept here so the Free
# Agents module is self-contained (no cross-screen import).
# ============================================================
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

    Mirrors roster.py:_abbreviate_wc (P0-1 — Free Agents + Roster
    must use the same abbreviation scheme so the two sister screens
    read as a pair).
    """
    if not wc_name:
        return ""
    key = str(wc_name).strip().lower()
    if key in _WC_ABBREVIATIONS:
        return _WC_ABBREVIATIONS[key]
    return str(wc_name).strip()[:3].upper()


# ============================================================
# UI Implementation Plan v3 — P0-1: short phrases for Stage, Ceiling,
# Form. Mirrors the Roster's Stage + Form maps (kept locally so the
# Free Agents module is self-contained). Ceiling is Free Agents-only
# (replaces the Roster's "Form" mirror with the Potential column's
# short phrase).
# ============================================================

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

# Map canonical potential_desc label → short Ceiling phrase. The
# interpretation layer hasn't been extended to populate
# fighter_descriptors.potential_desc as of schema 3.12.0 (the column
# is NULL across the seeded DB) — so the default fallback "(Uncached)"
# is the most common display until that extension lands. The map
# covers the labels the future interpretation extension will use
# (mirrors the band-threshold approach used by the other descriptors).
_CEILING_SHORT_PHRASES = {
    "elite": "Elite",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "bust_risk": "Bust Risk",
}


def _stage_short_phrase(stored_value):
    """Decode a career_phase cache value to a short Stage phrase.

    Mirrors roster.py:_stage_short_phrase. Defensive — NULL /
    unrecognized values render as "(Uncached)".
    """
    if not stored_value or "||" not in str(stored_value):
        return "(Uncached)"
    label = str(stored_value).split("||", 1)[0]
    return _STAGE_SHORT_PHRASES.get(label, "(Uncached)")


def _form_short_phrase(stored_value):
    """Decode a momentum cache value to a short Form phrase.

    Mirrors roster.py:_form_short_phrase. Defensive — NULL /
    unrecognized values render as "(Uncached)".
    """
    if not stored_value or "||" not in str(stored_value):
        return "(Uncached)"
    label = str(stored_value).split("||", 1)[0]
    return _FORM_SHORT_PHRASES.get(label, "(Uncached)")


def _ceiling_short_phrase(stored_value):
    """Decode a potential_desc cache value to a short Ceiling phrase.

    P0-1: the Free Agents screen renames the "Potential" column to
    "Ceiling" + uses short phrases (e.g., "Elite", "High") instead of
    the long-form voice phrase. Per D1: as of schema 3.12.0 the
    potential_desc column is NULL across the seeded DB — the
    interpretation layer hasn't been extended to populate it yet. The
    fallback "(Uncached)" surfaces this so the player sees the same
    information asymmetry WMMA5 + EWMMA use: the player can't see a
    free agent's ceiling until they scout them.
    """
    if not stored_value or "||" not in str(stored_value):
        return "(Uncached)"
    label = str(stored_value).split("||", 1)[0]
    return _CEILING_SHORT_PHRASES.get(label, "(Uncached)")


# ============================================================
# UI Implementation Plan v3 — P0-1: age computation (mirrors Roster).
# ============================================================
def _compute_age_from_dob(dob_str, sim_date_str):
    """Compute a fighter's age as of the sim date.

    Mirrors roster.py:_compute_age_from_dob. Lives here so the Free
    Agents module is self-contained (no cross-screen import).
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
# HELPERS (mirrors roster.py — shared with the Free Agents screen
# because the display conventions are identical)
# ============================================================

def _format_name(first, last, nickname):
    """Format a fighter's name with optional nickname in quotes.

    "Hiroki Nakamura \"Mist\"" — matches the display convention used
    in the Dashboard's Fighter Watch + the Roster. Defensive — any
    None components are skipped (some fighters have no nickname).
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


def _format_record(wins, losses, draws):
    """Format a fighter's record as 'W-L-D'.

    Per §14: career stats (record) are explicitly OK to display as
    numbers — they're not attribute values. Defensive — any None
    components default to 0.
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
    doesn't contain "||", return the caller-provided fallback.
    """
    phrase = decode_phrase(stored_value)
    return phrase if phrase else fallback


# ============================================================
# UI Implementation Plan v3 — P0-1: promotion logo loader + name
# formatting helpers (mirrors roster.py).
# ============================================================

def _format_name_short(first, last):
    """Format a fighter's name as 'First Last' (no nickname).

    Mirrors roster.py:_format_name_short. P0-1: the new FighterTable's
    Name column drops the nickname (the table is data-dense; nicknames
    clutter the column). The nickname is still shown on the Fighter
    Profile.
    """
    parts = []
    if first:
        parts.append(str(first).strip())
    if last:
        parts.append(str(last).strip())
    return " ".join(parts).strip() or "Unknown"


def _load_promo_logo(promo_id, promo_name, size=60):
    """Load + resize a promotion logo for the Free Agents header.

    Mirrors roster.py:_load_promo_logo. P0-1: the Free Agents screen
    now has a 60x60 promo logo at the top, matching the Roster, so
    the two sister screens read as a pair.
    """
    if not HAS_PIL or promo_id is None:
        return None
    try:
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


# ============================================================
# FREE AGENTS SCREEN
# ============================================================

class FreeAgentsScreen(ctk.CTkFrame):
    """Free Agents — the unsigned-fighter pool, interpretation-first.

    The Talent Hunter's hunting ground. Office Mode only (NOT a
    Fight Night screen). Registered with GameState as 'free_agents'.
    The refresh callback (`_refresh`) re-queries the free-agent pool
    (filtered + searched + paginated) + re-renders the Treeview.

    Usage:
        screen = FreeAgentsScreen(parent_frame)
        state.register_screen("free_agents", screen, screen._refresh)
        state.set_active_screen("free_agents")
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Background — match Office Mode base (cards sit on top).
        theme = get_theme()
        self.configure(fg_color=theme.colors.bg_base)

        # Filter + pagination state. Survives across _refresh() calls
        # so the player's view is preserved when they navigate to
        # Fighter Profile and back. See D5, D7, D10.
        self._current_page = 1
        self._weight_class_filter = None  # None = "All Weight Classes"
        # UI Fix Plan 2 — Phase 1, Fix 10: default gender filter to
        # "male" (was None = "All"). Mirrors the same change in
        # roster.py for consistency — both screens now show the male
        # cohort first, with the dropdown available for "Female" /
        # "All" switching. See roster.py for the full rationale.
        self._gender_filter = "male"
        self._search_term = ""
        self._sort_column = "fighter_id"  # default: insertion order
        self._sort_reverse = False

        # Cached free-agent data (list of dicts). Refreshed by
        # _refresh(). Kept as an attribute so the sort handler can
        # re-sort without re-querying the DB.
        self._fa_data = []

        self._pagination_label = None
        self._prev_button = None
        self._next_button = None
        self._subtitle_label = None
        self._weight_class_menu = None
        # Per UI-POLISH Fix 2: gender filter dropdown.
        self._gender_menu = None
        # Per UI-POLISH Fix 3: View Profile button (alongside Sign).
        self._view_profile_button = None
        self._search_entry = None
        self._sign_button = None
        self._status_label = None

        # UI Implementation Plan v3 — P0-1: the new FighterTable
        # widget. Built by _build_table. Holds the row data the
        # FighterTable renders (set_rows replaces the Treeview's
        # insert/clear cycle).
        # P2-3: the legacy ttk.Treeview path + USE_TREEVIEW flag were
        # deleted — FighterTable is now the only table implementation.
        self._fighter_table = None

        # UI Implementation Plan v3 — P0-1: promotion logo image
        # reference. Kept as an attribute so the GC doesn't drop the
        # underlying Tk image (Tk images are referenced by name, not
        # Python refcount). Built by _refresh_subtitle (which has the
        # promo_id needed to resolve the logo file).
        self._promo_logo_ctk_image = None
        # Per-Fix-9 promotion name cache (mirrors roster.py).
        self._cached_promo_name = None

        # UI Implementation Plan v3 — P0-1: cached sim date string
        # (used for age computation in _render_table_new). Refreshed
        # by _refresh before rendering the table.
        self._sim_date_str = None

        # Build the static structure. Dynamic content (Treeview rows,
        # pagination label, weight-class dropdown values) is rendered
        # by _refresh.
        self._build_header()
        self._build_filter_row()
        self._build_table()
        self._build_pagination()
        self._build_sign_bar()
        self._build_footer()

        # Initial render. after(50, ...) so the widget is fully laid
        # out before we query (matches DashboardScreen + RosterScreen).
        self.after(50, self._refresh)

    # ============================================================
    # SECTION 1 — HEADER (H1 title + count subtitle)
    # ============================================================

    def _build_header(self):
        """Build the H1 title + subtitle ('OPEN MARKET' + count).

        UI Fix Plan 2 — Phase 3, Fix 12 + Fix 2: H1 title renamed from
        'FREE AGENTS' to 'OPEN MARKET' to match the NAV_GROUPS display
        name + the plan's Voice Recommendations table. The screen-name
        key 'free_agents' is unchanged so state.set_active_screen +
        refresh registrations still work.

        UI Implementation Plan v3 — P0-1: added a 60x60 promotion logo
        at the top (mirrors the Roster's header). The Free Agents + the
        Roster are sister screens — they should look like a pair.
        """
        theme = get_theme()

        # Header row: title + optional promotion logo (P0-1).
        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # ---- Promotion logo (P0-1 — mirrors the Roster) ----
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
            title_subtitle_stack, text="OPEN MARKET",
            font=theme.fonts.display_small, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x")

        # Subtitle populated by _refresh (needs the count from the DB).
        self._subtitle_label = ctk.CTkLabel(
            title_subtitle_stack, text="Loading free agents...",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", pady=(2, 0))

    # ============================================================
    # SECTION 2 — FILTER ROW (weight-class dropdown + search entry)
    # ============================================================

    def _build_filter_row(self):
        """Build the filter row: gender + weight-class + search entry.

        Same layout as the Roster (D4 in roster.py), plus a gender
        dropdown (UI-POLISH Fix 2):
          [Gender: ▼ All]  [Weight Class: ▼ All WC]  [Search: [___]]
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
        # re-queries the weight classes present in the FREE AGENT pool
        # on every render — handles changes from signings).
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

        search_label = ctk.CTkLabel(
            filter_row, text="Search:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
        )
        search_label.pack(side="left", padx=(0, 8))

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
    # SECTION 3 — TABLE (ttk.Treeview — D9, OR FighterTable — P0-1)
    # ============================================================

    def _build_table(self):
        """Build the free-agents table.

        UI Implementation Plan v3 — P2-3: the legacy ttk.Treeview
        path + USE_TREEVIEW flag were deleted. FighterTable is now
        the only table implementation. This method is kept as a thin
        wrapper around _build_table_new so existing call sites stay
        valid (mirrors roster.py's pattern).
        """
        self._build_table_new()

    def _build_table_new(self):
        """Build the new FighterTable-based free-agents table (P0-1).

        Mirrors the Roster's _build_table_new — same column layout +
        same widget config so the two sister screens read as a pair.
        The only column-set difference: Free Agents shows "Ceiling"
        (the renamed Potential column) where the Roster shows nothing
        equivalent (the Roster doesn't display potential — the player
        already signed those fighters + knows their ceiling).

        Column layout per P0-1:
          Name (220px, hyperlink) | Age (50px) | WC (60px) |
          Stage (140px) | Ceiling (130px) | Form (120px) | Record (80px)
        """
        theme = get_theme()

        # Container card — gives the FighterTable a framed surface.
        # QW2/QW3/QW7: bg_surface → bg_card (distinct from shell),
        # border_subtle 1px border, corner_radius=0 for sharp "ledger"
        # edges per UI_REDESIGN_VISUAL_PLAN §4.3.
        table_card = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_card_elevated, corner_radius=0,
            border_width=1, border_color=theme.colors.border_subtle,
        )
        table_card.pack(side="top", fill="both", expand=True,
                        padx=20, pady=(0, 10))

        # Build the column configs.
        columns = [
            Column(NEW_COL_NAME, NEW_COLUMN_LABELS[NEW_COL_NAME],
                   NEW_COLUMN_WIDTHS[NEW_COL_NAME],
                   NEW_COLUMN_ANCHORS[NEW_COL_NAME], hyperlink=True),
            Column(NEW_COL_AGE, NEW_COLUMN_LABELS[NEW_COL_AGE],
                   NEW_COLUMN_WIDTHS[NEW_COL_AGE],
                   NEW_COLUMN_ANCHORS[NEW_COL_AGE]),
            Column(NEW_COL_WC, NEW_COLUMN_LABELS[NEW_COL_WC],
                   NEW_COLUMN_WIDTHS[NEW_COL_WC],
                   NEW_COLUMN_ANCHORS[NEW_COL_WC]),
            Column(NEW_COL_STAGE, NEW_COLUMN_LABELS[NEW_COL_STAGE],
                   NEW_COLUMN_WIDTHS[NEW_COL_STAGE],
                   NEW_COLUMN_ANCHORS[NEW_COL_STAGE]),
            Column(NEW_COL_CEILING, NEW_COLUMN_LABELS[NEW_COL_CEILING],
                   NEW_COLUMN_WIDTHS[NEW_COL_CEILING],
                   NEW_COLUMN_ANCHORS[NEW_COL_CEILING]),
            Column(NEW_COL_FORM, NEW_COLUMN_LABELS[NEW_COL_FORM],
                   NEW_COLUMN_WIDTHS[NEW_COL_FORM],
                   NEW_COLUMN_ANCHORS[NEW_COL_FORM]),
            Column(NEW_COL_RECORD, NEW_COLUMN_LABELS[NEW_COL_RECORD],
                   NEW_COLUMN_WIDTHS[NEW_COL_RECORD],
                   NEW_COLUMN_ANCHORS[NEW_COL_RECORD]),
        ]

        # The FighterTable widget itself.
        # QW2: passes bg_card so the table interior matches the wrapper
        # card's tier (was bg_surface — same as the shell).
        self._fighter_table = FighterTable(
            table_card,
            columns=columns,
            on_row_click=self._on_row_click_new,
            on_row_double_click=self._on_row_double_click_new,
            on_sort_click=self._on_sort_click_new,
            page_size=PAGE_SIZE,
            empty_message="No free agents available.",
            fg_color=theme.colors.bg_card_elevated, corner_radius=0,
        )
        self._fighter_table.pack(side="top", fill="both", expand=True,
                                  padx=1, pady=1)

    # ============================================================
    # SECTION 4 — PAGINATION (Prev / Next + page indicator)
    # ============================================================

    def _build_pagination(self):
        """Build the pagination bar.

        Same layout as the Roster (D3 in roster.py):
          [← Prev]  Page 1 of 50  [Next →]
        """
        theme = get_theme()

        pagination_row = ctk.CTkFrame(self, fg_color="transparent")
        pagination_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

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

        self._pagination_label = ctk.CTkLabel(
            pagination_row, text="Page 1 of 1",
            font=theme.fonts.body,
            text_color=theme.colors.text_secondary,
        )
        self._pagination_label.pack(side="left", padx=20)

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
    # SECTION 5 — SIGN BAR (Sign Selected button + status label)
    # ============================================================

    def _build_sign_bar(self):
        """Build the Sign Selected Fighter bar (D2, D3, D4).

        Layout (per UI-POLISH Fix 3 — added a "View Profile" button
        alongside Sign, so the player can inspect a free agent before
        committing to signing them):
          [✚ Sign Selected Fighter]  [▶ View Profile]   Status: ...

        The Sign button is gold-themed (matches the top-bar Advance Day
        button — both are the dopamine buttons in their respective
        screens). Disabled when no row is selected.
        The View Profile button is neutral — opens the Fighter Profile
        screen for the selected fighter. Also disabled when no row is
        selected.
        """
        theme = get_theme()

        sign_row = ctk.CTkFrame(self, fg_color="transparent")
        sign_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Sign button — gold accent. Disabled initially (no selection).
        self._sign_button = ctk.CTkButton(
            sign_row, text="✚  Sign Selected Fighter",
            font=theme.fonts.body,
            width=220, height=32,
            corner_radius=6,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            state="disabled",
            command=self._on_sign_clicked,
        )
        self._sign_button.pack(side="left")

        # View Profile button (UI-POLISH Fix 3) — neutral elevated
        # surface. Disabled initially; enabled when a row is selected.
        self._view_profile_button = ctk.CTkButton(
            sign_row, text="▶  View Profile",
            font=theme.fonts.body,
            width=160, height=32,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            state="disabled",
            command=self._on_view_profile_clicked,
        )
        self._view_profile_button.pack(side="left", padx=(10, 0))

        # Status label — shows the last sign action's result.
        # Idle by default; updated by _on_sign_clicked.
        self._status_label = ctk.CTkLabel(
            sign_row, text="Select a fighter, then click Sign or View Profile.",
            font=theme.fonts.body_small,
            text_color=theme.colors.text_tertiary,
            anchor="w",
        )
        self._status_label.pack(side="left", padx=20)

    # ============================================================
    # SECTION 6 — FOOTER (click-to-view-profile hint)
    # ============================================================

    def _build_footer(self):
        """Build the footer hint: 'Single-click selects, double-click views'."""
        theme = get_theme()

        footer_label = ctk.CTkLabel(
            self,
            text="Single-click a fighter to select. Double-click (or click "
                 "View Profile) to inspect them. Click Sign to add them to your roster.",
            font=theme.fonts.caption,
            text_color=theme.colors.text_tertiary,
            anchor="w",
        )
        footer_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # HANDLERS — filter, search, sort, pagination, navigation, sign
    # ============================================================

    def _on_weight_class_change(self, choice):
        """Handle weight-class dropdown change.

        Resets to page 1 (page state resets when filter changes) +
        triggers _refresh.
        """
        if choice == "All Weight Classes":
            self._weight_class_filter = None
        else:
            # Extract the weight_class_id from the dropdown value.
            # _refresh populates the dropdown with "WC Name (id=N)"
            # format so we can parse the id back out.
            try:
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
        to 1.

        Phase 4 — Performance: @debounce(200) collapses fast typing
        into a single refresh (same pattern as Roster). The free
        agents pool is ~600 rows, so the per-keystroke cost is lower
        than Roster's 4450-row query, but rebuilding 120 widgets per
        keystroke is still noticeable on slower machines.
        """
        try:
            term = self._search_entry.get().strip()
        except Exception:
            term = ""
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

        Navigates to the Fighter Profile screen for the selected
        free agent. The fighter is NOT signed — the player is just
        inspecting them. This is the "look before you leap" affordance
        for the Talent Hunter fantasy.
        """
        self._navigate_to_selected_profile()

    # `View Profile` button click helper stays — used by both
    # _on_view_profile_clicked + _on_row_double_click_new.

    def _navigate_to_selected_profile(self):
        """Shared navigation helper — used by double-click + View Profile.

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

    def _on_sign_clicked(self):
        """Handle Sign Selected Fighter button click (D2, D3, D4).

        Per D3:
          1. Read the selected fighter_id (from the Treeview selection
             OR the FighterTable widget, depending on USE_TREEVIEW).
          2. Read the current sim date from simulation_clock.
          3. Call services.contracts.sign_free_agent(...).
          4. Commit the conn.
          5. Show a status message (success/failure).
          6. state.refresh_all() so Roster + Dashboard pick up the
             new signing.
          7. self._refresh() to update the Free Agents table.
        """
        try:
            # UI Implementation Plan v3 — P2-3: the Treeview fallback
            # was deleted. FighterTable is the only path — reads the
            # selected fighter_id directly from the widget.
            if self._fighter_table is None:
                self._set_status("Table not initialized.", "warning")
                return
            fighter_id = self._fighter_table.get_selected_fighter_id()
            if fighter_id is None:
                self._set_status("No fighter selected.", "warning")
                return

            state = get_state()
            conn = state.get_conn()
            if conn is None:
                self._set_status("Database unavailable.", "warning")
                return
            promo_id = state.get_player_promotion_id()

            # Read the current sim date — used as the contract start_date.
            # Per the D5 quirk in app.py: qualify the column as
            # simulation_clock.current_date so bare `current_date`
            # doesn't resolve to SQLite's built-in date function.
            current_date = None
            try:
                date_row = conn.execute(
                    "SELECT simulation_clock.current_date "
                    "FROM simulation_clock WHERE clock_id = 1"
                ).fetchone()
                if date_row and date_row[0]:
                    current_date = date_row[0]
            except sqlite3.Error:
                pass
            if not current_date:
                # Fallback to today's wall-clock date. Shouldn't happen
                # in a seeded DB but defensive.
                current_date = datetime.now().strftime("%Y-%m-%d")

            # Lazy import — services.contracts is in src/services/, on
            # the sys.path that app.py manipulates. We import here so
            # the screen module loads even if the services layer is
            # refactored.
            try:
                from services.contracts import sign_free_agent
            except ImportError:
                self._set_status(
                    "Contracts service unavailable — cannot sign.", "danger")
                return

            # Look up the fighter + promotion names for the status message.
            fighter_name = "Unknown fighter"
            try:
                row = conn.execute(
                    "SELECT first_name || ' ' || last_name FROM fighters "
                    "WHERE fighter_id = ?",
                    (fighter_id,),
                ).fetchone()
                if row and row[0]:
                    fighter_name = row[0]
            except sqlite3.Error:
                pass

            promo_name = "your promotion"
            try:
                row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id = ?",
                    (promo_id,),
                ).fetchone()
                if row and row[0]:
                    promo_name = row[0]
            except sqlite3.Error:
                pass

            # Call the sign_free_agent helper. The helper itself does
            # NOT commit — caller's responsibility per its docstring.
            contract_id = sign_free_agent(
                conn, fighter_id, promo_id, current_date,
                salary=DEFAULT_SIGNING_SALARY,
            )

            if contract_id is None:
                # The helper prints a warning to stdout explaining why
                # (retired / already signed / not active). Surface a
                # player-facing message too.
                self._set_status(
                    f"Could not sign {fighter_name} — they may have retired "
                    f"or signed elsewhere.",
                    "danger",
                )
                return

            # Commit the contract insert + fighter update + news item
            # insert + any event-bus side effects.
            try:
                conn.commit()
            except sqlite3.Error as e:
                self._set_status(
                    f"Signed but commit failed: {e}", "danger")
                return

            self._set_status(
                f"Signed {fighter_name} to {promo_name}.", "success")

            # Refresh all screens so the Roster + Dashboard pick up the
            # new signing immediately (the fighter is no longer a free
            # agent — they're on the player's roster).
            try:
                state.refresh_all()
            except Exception:
                # refresh_all failing shouldn't block the sign success.
                pass

            # Local refresh — remove the signed fighter from the table.
            # (state.refresh_all above already called self._refresh via
            # the registered callback, but call again to be safe — the
            # refresh is idempotent.)
            self._refresh()
        except Exception as e:
            print(f"Warning: sign handler failed: {e}", flush=True)
            self._set_status(f"Sign failed: {e}", "danger")

    # ============================================================
    # UI Implementation Plan v3 — P0-1: FighterTable handlers.
    # ============================================================

    def _on_sort_click_new(self, column_id, reverse):
        """Handle sort header click from the FighterTable (P0-1).

        Maps the new column ids (NEW_COL_NAME, NEW_COL_AGE, etc.) to
        the underlying sort_column value used by _sort_data. Then
        triggers _refresh which re-sorts + re-renders.
        """
        col_map = {
            NEW_COL_NAME: "fighter_id",  # name sort falls back to id
            NEW_COL_AGE: "age",
            NEW_COL_WC: COL_WC,
            NEW_COL_STAGE: COL_PHASE,
            NEW_COL_CEILING: COL_POTENTIAL,
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
        """Handle single-click on a FighterTable row (P0-1).

        Enables the Sign + View Profile buttons so the player can
        act on the selected fighter. The fighter name is also a
        HyperlinkLabel that fires its own navigation independently
        on direct click.
        """
        try:
            if fighter_id is not None:
                self._sign_button.configure(state="normal")
                self._view_profile_button.configure(state="normal")
            else:
                self._sign_button.configure(state="disabled")
                self._view_profile_button.configure(state="disabled")
        except Exception:
            pass

    def _on_row_double_click_new(self, fighter_id):
        """Handle double-click on a FighterTable row — navigate to profile.

        Per P0-1: the fighter name is already a hyperlink that
        navigates on single-click. Double-click anywhere in the row
        ALSO navigates (covers players who don't realize the name is
        a link). Mirrors roster.py:_on_row_double_click_new.
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
            toggle, fighter-signed).

        Safe to call repeatedly — clears old rows, re-queries,
        re-renders. Defensive against DB errors.

        UI Implementation Plan v3 — P2-3: the legacy ttk.Treeview
        render path was deleted. FighterTable.set_rows is the only
        render call (no USE_TREEVIEW branch needed).
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                return
            promo_id = state.get_player_promotion_id()

            # UI Implementation Plan v3 — P0-1: cache the sim date
            # string for age computation in _render_table_new. Read
            # once per refresh — used for every row's Age column.
            self._sim_date_str = self._read_sim_date(conn)

            # Populate the weight-class dropdown (D5). Done on every
            # refresh so newly-signed/cut fighters' weight classes
            # appear/disappear.
            self._refresh_weight_class_dropdown(conn)

            # Query the free agents (filtered + searched).
            self._fa_data = self._query_free_agents(conn)

            # Sort the data (D10).
            self._sort_data()

            # Clamp the current page to the last valid page.
            total_pages = self._total_pages()
            if self._current_page > total_pages:
                self._current_page = max(1, total_pages)

            # Render the current page of rows.
            self._render_table_new()
            self._refresh_pagination(total_pages)
            self._refresh_subtitle(len(self._fa_data), conn, promo_id)

            # After a re-render, the selection is gone — disable the
            # Sign + View Profile buttons until the player picks a new
            # row (UI-POLISH Fix 3 — View Profile added alongside Sign).
            try:
                if self._sign_button:
                    self._sign_button.configure(state="disabled")
                if self._view_profile_button:
                    self._view_profile_button.configure(state="disabled")
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: FreeAgentsScreen._refresh failed: {e}",
                  flush=True)

    def _read_sim_date(self, conn):
        """Read the current sim date from simulation_clock.

        P0-1: used for age computation in _render_table_new. Mirrors
        roster.py:_read_sim_date. Defensive — returns None on any
        query failure (the Age column will show blank for all rows,
        not a crash).
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
    # Subtitle — "N free agents available"
    # ------------------------------------------------------------

    def _refresh_subtitle(self, total_count, conn=None, promo_id=None):
        """Update the subtitle label with the count + promo logo (P0-1).

        P0-1: now also loads the promotion logo into
        self._promo_logo_label (60x60 PNG from
        src/ui/assets/promo_logos/). Mirrors the Roster's logo loader.
        Falls back to text initials if the logo isn't found or PIL
        isn't available.
        """
        try:
            theme = get_theme()
            promo_name = "Your Promotion"
            if conn is not None and promo_id is not None:
                try:
                    promo_row = conn.execute(
                        "SELECT name FROM promotions WHERE promotion_id=?",
                        (promo_id,),
                    ).fetchone()
                    if promo_row and promo_row[0]:
                        promo_name = promo_row[0]
                except sqlite3.Error:
                    pass

            text = f"{total_count:,} unsigned fighters available"
            self._subtitle_label.configure(
                text=text,
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )

            # ---- Promotion logo (P0-1 — mirrors the Roster) ----
            self._cached_promo_name = promo_name
            if conn is not None and promo_id is not None:
                self._refresh_promo_logo(promo_id, promo_name)
        except Exception as e:
            print(f"Warning: free agents subtitle refresh failed: {e}",
                  flush=True)

    def _refresh_promo_logo(self, promo_id, promo_name):
        """Load the promotion logo into the header logo label (P0-1).

        Mirrors roster.py:_refresh_promo_logo. Tries _load_promo_logo
        (PIL image resize). On success, wraps in CTkImage + sets on
        self._promo_logo_label. On failure, shows the promotion's
        initials (first letter of each word, up to 3 chars) as text.
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
            print(f"Warning: free agents promo logo refresh failed: {e}",
                  flush=True)

    @staticmethod
    def _promo_initials(promo_name):
        """Compute up to 3-letter initials from a promotion name.

        Mirrors roster.py:_promo_initials. "Alpha Combat Federation"
        → "ACF". Defensive — returns "?" if the name is empty.
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

    def _refresh_weight_class_dropdown(self, conn):
        """Populate the weight-class dropdown with the free-agent pool's
        weight classes.

        Per D5: lists every weight class present in the FREE AGENT pool
        (not the player's roster — different from the Roster's version
        of this method) + "All Weight Classes" as the first option.
        Values are formatted as "WC Name (gender) [id=N]" so we can
        extract the id when the player selects one.

        Per UI-POLISH Fix 2: when a gender filter is active, the
        dropdown only shows weight classes for that gender.
        """
        try:
            current_value = None
            try:
                current_value = self._weight_class_menu.get()
            except Exception:
                pass

            rows = []
            try:
                # Query weight classes present in the free-agent pool.
                # current_promotion_id IS NULL = free agent. If a
                # gender filter is active, filter by gender too.
                if self._gender_filter is not None:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT wc.weight_class_id, wc.name, wc.gender
                        FROM fighters f
                        JOIN weight_classes wc
                          ON wc.weight_class_id = f.weight_class_id
                        WHERE f.current_promotion_id IS NULL
                          AND f.is_active = 1
                          AND f.is_retired = 0
                          AND f.gender = ?
                        ORDER BY wc.display_order ASC, wc.name ASC
                        """,
                        (self._gender_filter,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT wc.weight_class_id, wc.name, wc.gender
                        FROM fighters f
                        JOIN weight_classes wc
                          ON wc.weight_class_id = f.weight_class_id
                        WHERE f.current_promotion_id IS NULL
                          AND f.is_active = 1
                          AND f.is_retired = 0
                        ORDER BY wc.display_order ASC, wc.name ASC
                        """,
                    ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: free-agent weight-class query failed: {e}",
                      flush=True)

            values = ["All Weight Classes"]
            for wc_id, wc_name, wc_gender in rows:
                gender_tag = f" ({wc_gender})" if wc_gender else ""
                values.append(f"{wc_name}{gender_tag} [id={wc_id}]")

            self._weight_class_menu.configure(values=values)

            if current_value and current_value in values:
                self._weight_class_menu.set(current_value)
            else:
                self._weight_class_menu.set("All Weight Classes")
                self._weight_class_filter = None
        except Exception as e:
            print(f"Warning: free-agent weight-class dropdown refresh "
                  f"failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Query the free agents (filtered + searched)
    # ------------------------------------------------------------

    def _query_free_agents(self, conn):
        """Query the free agents with the current filter + search applied.

        Per D1: reads from fighters + fighter_descriptors (cache) +
        fighter_career (career stats only) + weight_classes (game
        state). NEVER reads from fighter_attributes /
        fighter_personality / fighter_bios / fighter_contracts.

        Returns:
            List of dicts, one per fighter. Each dict has keys:
                fighter_id, name, weight_class_name, career_phase_stored,
                momentum_stored, potential_stored, record_wins,
                record_losses, record_draws.
            The "_stored" values are the raw "label||phrase" cache
            values — decode_phrase() is applied at render time so
            sorting can use the canonical label if needed (D10).
        """
        rows = []
        try:
            where_clauses = [
                "f.current_promotion_id IS NULL",
                "f.is_active = 1",
                "f.is_retired = 0",
            ]
            params = []

            if self._weight_class_filter is not None:
                where_clauses.append("f.weight_class_id = ?")
                params.append(self._weight_class_filter)

            # Per UI-POLISH Fix 2: gender filter. Applied in SQL.
            if self._gender_filter is not None:
                where_clauses.append("f.gender = ?")
                params.append(self._gender_filter)

            if self._search_term:
                # Case-insensitive substring on first_name + last_name
                # + nickname. SQLite's LIKE is case-insensitive for
                # ASCII by default.
                like_term = f"%{self._search_term}%"
                where_clauses.append(
                    "(f.first_name LIKE ? OR f.last_name LIKE ? "
                    "OR f.nickname LIKE ?)"
                )
                params.extend([like_term, like_term, like_term])

            where_sql = " AND ".join(where_clauses)

            # Per §17.3, fighters / fighter_career / weight_classes
            # are simulation tables (the interpretation layer never
            # writes to them). The Free Agents screen reads ONLY from:
            #   - fighters: first_name, last_name, nickname,
            #     weight_class_id, current_promotion_id, is_active,
            #     is_retired (game state — names + classification,
            #     NOT attribute values per §14)
            #   - fighter_descriptors: career_phase, momentum,
            #     potential_desc voice phrases (cache — §17.3 cache
            #     table)
            #   - fighter_career: record_wins, record_losses,
            #     record_draws (career stats — explicitly OK per §14).
            #     NEVER reads `potential` (raw 0-100 — §14-protected).
            #   - weight_classes: name (game state)
            sql = f"""
                SELECT f.fighter_id, f.first_name, f.last_name, f.nickname,
                       f.date_of_birth,
                       wc.name AS weight_class_name,
                       fd.career_phase, fd.momentum, fd.potential_desc,
                       fc.record_wins, fc.record_losses, fc.record_draws
                FROM fighters f
                LEFT JOIN weight_classes wc
                  ON wc.weight_class_id = f.weight_class_id
                LEFT JOIN fighter_descriptors fd
                  ON fd.fighter_id = f.fighter_id
                LEFT JOIN fighter_career fc
                  ON fc.fighter_id = f.fighter_id
                WHERE {where_sql}
                ORDER BY f.fighter_id ASC
            """
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: free-agent query failed: {e}", flush=True)
            return []

        fa_list = []
        for r in rows:
            (fid, first, last, nick, dob, wc_name, phase_stored, mom_stored,
             pot_stored, wins, losses, draws) = r
            fa_list.append({
                "fighter_id": fid,
                "name": _format_name(first, last, nick),
                "name_short": _format_name_short(first, last),
                "date_of_birth": dob,
                "weight_class_name": wc_name or "Unknown",
                "career_phase_stored": phase_stored,
                "momentum_stored": mom_stored,
                "potential_stored": pot_stored,
                "record_wins": wins,
                "record_losses": losses,
                "record_draws": draws,
            })
        return fa_list

    # ------------------------------------------------------------
    # Sort the data (D10)
    # ------------------------------------------------------------

    def _sort_data(self):
        """Sort self._fa_data by self._sort_column.

        Per D10: sort is applied in Python (not SQL) because the voice
        phrases need decode_phrase() before sorting — sorting raw
        "label||phrase" strings would sort by the canonical label, not
        the player-facing phrase, which is unintuitive.

        Sort keys:
          - fighter_id (default) → int, ascending
          - name → string, case-insensitive
          - weight_class_name → string, case-insensitive
          - career_phase → decoded phrase (or "" if None)
          - potential → decoded phrase (or "" if None)
          - record → total fights (wins + losses + draws)
          - momentum → decoded phrase (or "" if None)
        """
        col = self._sort_column
        reverse = self._sort_reverse

        def sort_key(item):
            if col == "fighter_id":
                return item["fighter_id"]
            if col == "age":
                # P0-1: sort by computed age. Defensive — fighters
                # with bad DOB get age 0 (sorts first ascending).
                age_str = _compute_age_from_dob(
                    item.get("date_of_birth"), self._sim_date_str)
                try:
                    return int(age_str) if age_str else 0
                except (TypeError, ValueError):
                    return 0
            if col == COL_WC:
                return item["weight_class_name"].lower()
            if col == COL_PHASE:
                return _phrase_or_fallback(
                    item["career_phase_stored"], "") or ""
            if col == COL_POTENTIAL:
                return _phrase_or_fallback(
                    item["potential_stored"], "") or ""
            if col == COL_RECORD:
                total = (item["record_wins"] or 0) + \
                        (item["record_losses"] or 0) + \
                        (item["record_draws"] or 0)
                return total
            if col == COL_MOMENTUM:
                return _phrase_or_fallback(
                    item["momentum_stored"], "") or ""
            return 0

        try:
            self._fa_data.sort(key=sort_key, reverse=reverse)
        except (TypeError, ValueError) as e:
            print(f"Warning: free-agent sort failed, falling back: {e}",
                  flush=True)
            self._fa_data.sort(key=lambda x: x["fighter_id"])

    # ------------------------------------------------------------
    # Render the table (current page of rows)
    # ------------------------------------------------------------

    def _render_table_new(self):
        """Render the current page of rows into the FighterTable (P0-1).

        Mirrors roster.py:_render_table_new. Builds a list of row
        dicts (one per fighter on the current page) + passes them to
        FighterTable.set_rows. The widget handles the actual widget
        creation (HyperlinkLabel for the Name column, plain CTkLabel
        for the others).

        Per P0-1: computes Age from date_of_birth + sim date, applies
        the short Stage / Ceiling / Form phrases, abbreviates WC.

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
            page_rows = self._fa_data[start:end]

            if not page_rows:
                # Empty state (D6). Pass an empty list + the
                # appropriate empty message based on WHY the pool
                # is empty.
                empty_msg = self._empty_state_message()
                self._fighter_table.set_rows([], empty_message=empty_msg)
                return

            # Build the row dicts for the FighterTable.
            rows = []
            for fighter in page_rows:
                # Per P0-1: compute age from DOB + sim date.
                age_str = _compute_age_from_dob(
                    fighter.get("date_of_birth"), self._sim_date_str)
                # Per P0-1: abbreviate weight class.
                wc_abbr = _abbreviate_wc(fighter["weight_class_name"])
                # Per P0-1: short Stage / Ceiling / Form phrases.
                stage_phrase = _stage_short_phrase(
                    fighter["career_phase_stored"])
                ceiling_phrase = _ceiling_short_phrase(
                    fighter["potential_stored"])
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
                    NEW_COL_WC: wc_abbr,
                    NEW_COL_STAGE: stage_phrase,
                    NEW_COL_CEILING: ceiling_phrase,
                    NEW_COL_FORM: form_phrase,
                    NEW_COL_RECORD: record_str,
                })

            self._fighter_table.set_rows(rows)
        except Exception as e:
            print(f"Warning: free-agent table render (new) failed: {e}",
                  flush=True)

    def _empty_state_message(self):
        """Return the appropriate empty-state message (D6).

        - No free agents at all → "No free agents available. Advance
          a few days — contracts expire and fighters become available."
        - Filter excludes everyone → "No free agents match this weight
          class."
        - Search excludes everyone → "No free agents match '<term>'.
          Try a different name."
        """
        try:
            state = get_state()
            conn = state.get_conn()
            total = conn.execute(
                "SELECT COUNT(*) FROM fighters "
                "WHERE current_promotion_id IS NULL "
                "AND is_active = 1 AND is_retired = 0",
            ).fetchone()[0]
        except Exception:
            total = 0

        if total == 0:
            return ("No free agents available. Advance a few days — "
                    "contracts expire and fighters become available.")
        if self._search_term:
            return (f"No free agents match '{self._search_term}'. "
                    f"Try a different name.")
        if self._weight_class_filter is not None:
            return "No free agents match this weight class."
        return "No free agents match the current view."

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

            self._prev_button.configure(
                state="normal" if self._current_page > 1 else "disabled"
            )
            self._next_button.configure(
                state="normal" if self._current_page < total_pages else "disabled"
            )
        except Exception as e:
            print(f"Warning: free-agent pagination refresh failed: {e}",
                  flush=True)

    def _total_pages(self):
        """Return the total number of pages based on the current data."""
        total_fighters = len(self._fa_data)
        if total_fighters == 0:
            return 0
        return (total_fighters + PAGE_SIZE - 1) // PAGE_SIZE

    # ------------------------------------------------------------
    # Status feedback (D4)
    # ------------------------------------------------------------

    def _set_status(self, message, level="info"):
        """Update the status label with a color-coded message (D4).

        Args:
            message: the text to display.
            level: one of "info" (tertiary text), "success" (gold),
                "warning" (warning yellow), "danger" (crimson).
        """
        try:
            theme = get_theme()
            color_map = {
                "info": theme.colors.text_tertiary,
                "success": theme.colors.gold,
                "warning": theme.colors.warning,
                "danger": theme.colors.crimson,
            }
            color = color_map.get(level, theme.colors.text_tertiary)
            self._status_label.configure(
                text=message,
                font=theme.fonts.body_small,
                text_color=color,
            )
        except Exception as e:
            print(f"Warning: free-agent status update failed: {e}",
                  flush=True)
