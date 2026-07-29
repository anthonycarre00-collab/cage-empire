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

import customtkinter as ctk
import tkinter.ttk as ttk

from ui.theme import get_theme
from ui.state import get_state

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (mirrors
# DashboardScreen's D4 + RosterScreen's D4).
from interpretation.context_engine import decode_phrase


# ============================================================
# CONSTANTS
# ============================================================

# Page size — matches the Roster (D3 in roster.py: "show 20 at a time").
PAGE_SIZE = 20

# Default salary for sign_free_agent (matches the seed default in
# sign_free_agent's docstring + the seed_data.py _seed_default_fighter_
# contract helper). No negotiation flow yet — that's a future task.
DEFAULT_SIGNING_SALARY = 50000.0

# Treeview column identifiers. Same naming convention as the Roster
# (D2 in roster.py) so the pattern is recognisable across screens.
COL_NAME = "name"
COL_WC = "weight_class"
COL_PHASE = "career_phase"
COL_POTENTIAL = "potential"
COL_RECORD = "record"
COL_MOMENTUM = "momentum"

# Column display labels (heading text).
COLUMN_LABELS = {
    COL_NAME: "Name",
    COL_WC: "Weight Class",
    COL_PHASE: "Career Phase",
    COL_POTENTIAL: "Potential",
    COL_RECORD: "Record",
    COL_MOMENTUM: "Momentum",
}

# Column widths (in px). Tuned for a 1400px-wide main content area
# (~1360px after the sidebar). The Name column is widest (fighters
# have long names + nicknames); the Record column is narrowest
# ("18-5-0" is 7 chars). The Potential column is wider than the
# Roster's Narrative column because voice phrases can be long
# ("high-end potential with room to grow").
COLUMN_WIDTHS = {
    COL_NAME: 220,
    COL_WC: 130,
    COL_PHASE: 220,
    COL_POTENTIAL: 220,
    COL_RECORD: 80,
    COL_MOMENTUM: 180,
}


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
        self._search_term = ""
        self._sort_column = "fighter_id"  # default: insertion order
        self._sort_reverse = False

        # Cached free-agent data (list of dicts). Refreshed by
        # _refresh(). Kept as an attribute so the sort handler can
        # re-sort without re-querying the DB.
        self._fa_data = []

        # Treeview widget — built once in _build_table. Re-themed on
        # every _refresh() so theme-change refresh picks up new colors.
        self._treeview = None
        self._pagination_label = None
        self._prev_button = None
        self._next_button = None
        self._subtitle_label = None
        self._weight_class_menu = None
        self._search_entry = None
        self._empty_label = None
        self._sign_button = None
        self._status_label = None

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
        """Build the H1 title + subtitle ('FREE AGENTS' + count)."""
        theme = get_theme()

        title = ctk.CTkLabel(
            self, text="FREE AGENTS",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # Subtitle populated by _refresh (needs the count from the DB).
        self._subtitle_label = ctk.CTkLabel(
            self, text="Loading free agents...",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # SECTION 2 — FILTER ROW (weight-class dropdown + search entry)
    # ============================================================

    def _build_filter_row(self):
        """Build the filter row: weight-class dropdown + search entry.

        Same layout as the Roster (D4 in roster.py):
          [Weight Class: ▼ All Weight Classes]  [Search: [_______]]
        """
        theme = get_theme()

        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

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
    # SECTION 3 — TABLE (ttk.Treeview — D9)
    # ============================================================

    def _build_table(self):
        """Build the free-agents table.

        Same structure as the Roster (D2 in roster.py). 6 columns,
        headings only (no tree column), height=20 rows. Themed via
        a separate `FreeAgents.Treeview` style name so the two
        screens can be themed independently if a future task needs it.
        """
        theme = get_theme()

        table_card = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        table_card.pack(side="top", fill="both", expand=True, padx=20, pady=(0, 10))

        self._apply_treeview_style()

        self._treeview = ttk.Treeview(
            table_card,
            columns=(COL_NAME, COL_WC, COL_PHASE, COL_POTENTIAL,
                     COL_RECORD, COL_MOMENTUM),
            show="headings",
            style="FreeAgents.Treeview",
            height=PAGE_SIZE,
            selectmode="browse",
        )

        # Configure columns: width, anchor, heading text + sort command.
        # Name + WC + Phase + Potential + Momentum are left-anchored
        # (text); Record is center-anchored (short numeric-ish string).
        for col in (COL_NAME, COL_WC, COL_PHASE, COL_POTENTIAL,
                    COL_RECORD, COL_MOMENTUM):
            self._treeview.heading(
                col, text=COLUMN_LABELS[col],
                command=lambda c=col: self._on_heading_click(c),
            )
            anchor = "center" if col == COL_RECORD else "w"
            self._treeview.column(
                col, width=COLUMN_WIDTHS[col], anchor=anchor,
                stretch=False,
            )

        self._treeview.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)

        scrollbar = ctk.CTkScrollbar(
            table_card, command=self._treeview.yview,
            fg_color=theme.colors.bg_surface,
        )
        scrollbar.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self._treeview.configure(yscrollcommand=scrollbar.set)

        # Bind double-click → navigate to Fighter Profile (D8).
        self._treeview.bind("<Double-1>", self._on_row_double_click)
        # Bind single-click selection → enable the Sign button (D2).
        self._treeview.bind("<<TreeviewSelect>>", self._on_row_select)

        # Empty-state label — shown when no free agents match the
        # filter/search. Packed into the table_card so it overlays the
        # Treeview area. Hidden by _refresh when rows exist.
        self._empty_label = ctk.CTkLabel(
            table_card,
            text="No free agents available.",
            font=theme.fonts.body,
            text_color=theme.colors.text_tertiary,
            justify="center",
        )
        # Note: _empty_label is NOT packed here. _refresh decides.

    def _apply_treeview_style(self):
        """Apply the dark Office theme to the FreeAgents.Treeview style.

        Mirrors RosterScreen._apply_treeview_style (D2 in roster.py).
        Separate style name so the two screens can be themed
        independently. Idempotent — safe to call multiple times.
        """
        theme = get_theme()
        try:
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass  # clam may already be in use; that's fine

            style.configure(
                "FreeAgents.Treeview",
                background=theme.colors.bg_surface,
                foreground=theme.colors.text_primary,
                fieldbackground=theme.colors.bg_surface,
                bordercolor=theme.colors.bg_border,
                rowheight=28,
                font=("Inter", 12),
            )
            style.map(
                "FreeAgents.Treeview",
                background=[("selected", theme.colors.bg_surface_elevated)],
                foreground=[("selected", theme.colors.text_primary)],
            )
            style.configure(
                "FreeAgents.Treeview.Heading",
                background=theme.colors.bg_surface_elevated,
                foreground=theme.colors.gold,
                bordercolor=theme.colors.bg_border,
                relief="flat",
                font=("Inter", 13, "bold"),
            )
            style.map(
                "FreeAgents.Treeview.Heading",
                background=[("active", theme.colors.steel)],
            )
        except Exception as e:
            print(f"Warning: Treeview style setup failed: {e}", flush=True)

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

        Layout:
          [Sign Selected Fighter]   Status: ...

        The button is gold-themed (matches the top-bar Advance Day
        button — both are the dopamine buttons in their respective
        screens). Disabled when no row is selected.
        """
        theme = get_theme()

        sign_row = ctk.CTkFrame(self, fg_color="transparent")
        sign_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Sign button — gold accent. Disabled initially (no selection).
        self._sign_button = ctk.CTkButton(
            sign_row, text="✚  Sign Selected Fighter",
            font=theme.fonts.body,
            width=200, height=32,
            corner_radius=6,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            state="disabled",
            command=self._on_sign_clicked,
        )
        self._sign_button.pack(side="left")

        # Status label — shows the last sign action's result.
        # Idle by default; updated by _on_sign_clicked.
        self._status_label = ctk.CTkLabel(
            sign_row, text="Select a fighter, then click Sign.",
            font=theme.fonts.body_small,
            text_color=theme.colors.text_tertiary,
            anchor="w",
        )
        self._status_label.pack(side="left", padx=20)

    # ============================================================
    # SECTION 6 — FOOTER (click-to-view-profile hint)
    # ============================================================

    def _build_footer(self):
        """Build the footer hint: 'Double-click to view profile'."""
        theme = get_theme()

        footer_label = ctk.CTkLabel(
            self,
            text="Double-click a fighter to view their profile.  "
                 "Single-click selects, then Sign Selected to add them to your roster.",
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

    def _on_search_change(self, event=None):
        """Handle search-entry keystroke.

        Reads the current entry value + triggers _refresh. Page resets
        to 1. No manual debounce — the GUI event loop naturally
        throttles keystroke events for 600 rows.
        """
        try:
            term = self._search_entry.get().strip()
        except Exception:
            term = ""
        if term != self._search_term:
            self._search_term = term
            self._current_page = 1
            self._refresh()

    def _on_heading_click(self, col):
        """Handle heading click — sort by that column (D10)."""
        if self._sort_column == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = col
            self._sort_reverse = False
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

    def _on_row_select(self, event=None):
        """Handle single-click row selection — enable the Sign button.

        Per D2: the Sign button reads the Treeview selection to
        recover the fighter_id. Disabled when no row is selected
        (e.g., after _refresh clears the selection).
        """
        try:
            selection = self._treeview.selection()
            if selection:
                self._sign_button.configure(state="normal")
            else:
                self._sign_button.configure(state="disabled")
        except Exception:
            pass

    def _on_row_double_click(self, event=None):
        """Handle double-click on a Treeview row — navigate to profile.

        Mirrors RosterScreen._on_row_double_click (D7 in roster.py).
        Reads the selected row's fighter_id (stored as the Treeview
        item's iid), calls set_fighter_id() on the Fighter Profile
        screen, then navigates via state.set_active_screen.
        """
        try:
            selection = self._treeview.selection()
            if not selection:
                return
            try:
                fighter_id = int(selection[0])
            except (ValueError, IndexError):
                return

            state = get_state()
            profile_screen = state.get_screen("fighter_profile")
            if profile_screen is not None and hasattr(
                profile_screen, "set_fighter_id"
            ):
                profile_screen.set_fighter_id(fighter_id)

            state.set_active_screen("fighter_profile")
        except ValueError as e:
            print(f"Warning: navigation to fighter_profile failed: {e}",
                  flush=True)
        except Exception as e:
            print(f"Warning: row double-click handler failed: {e}",
                  flush=True)

    def _on_sign_clicked(self):
        """Handle Sign Selected Fighter button click (D2, D3, D4).

        Per D3:
          1. Read the selected fighter_id from the Treeview selection.
          2. Read the current sim date from simulation_clock.
          3. Call services.contracts.sign_free_agent(...).
          4. Commit the conn.
          5. Show a status message (success/failure).
          6. state.refresh_all() so Roster + Dashboard pick up the
             new signing.
          7. self._refresh() to update the Free Agents table.
        """
        try:
            selection = self._treeview.selection()
            if not selection:
                self._set_status("No fighter selected.", "warning")
                return
            try:
                fighter_id = int(selection[0])
            except (ValueError, IndexError):
                self._set_status("Invalid selection.", "warning")
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

        Safe to call repeatedly — clears old Treeview rows, re-queries,
        re-renders. Defensive against DB errors.
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                return

            # Re-apply the Treeview style on every refresh so theme-
            # change refresh picks up new colors (D9).
            self._apply_treeview_style()

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
            self._render_table()
            self._refresh_pagination(total_pages)
            self._refresh_subtitle(len(self._fa_data))

            # After a re-render, the selection is gone — disable the
            # Sign button until the player picks a new row.
            try:
                if self._sign_button:
                    self._sign_button.configure(state="disabled")
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: FreeAgentsScreen._refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Subtitle — "N free agents available"
    # ------------------------------------------------------------

    def _refresh_subtitle(self, total_count):
        """Update the subtitle label with the count."""
        try:
            theme = get_theme()
            text = f"{total_count:,} unsigned fighters available"
            self._subtitle_label.configure(
                text=text,
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )
        except Exception as e:
            print(f"Warning: free agents subtitle refresh failed: {e}",
                  flush=True)

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
                # current_promotion_id IS NULL = free agent.
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
            (fid, first, last, nick, wc_name, phase_stored, mom_stored,
             pot_stored, wins, losses, draws) = r
            fa_list.append({
                "fighter_id": fid,
                "name": _format_name(first, last, nick),
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
            if col == "fighter_id" or col == COL_NAME:
                if col == "fighter_id":
                    return item["fighter_id"]
                return item["name"].lower()
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

    def _render_table(self):
        """Render the current page of rows into the Treeview.

        Per D7: shows PAGE_SIZE (20) rows per page. The Treeview
        item's iid IS the fighter_id (so the double-click + sign
        handlers can recover it without a separate lookup).

        Per D6: empty-state handling — if no rows match the current
        filter/search, show the empty-state label.
        """
        try:
            try:
                self._treeview.delete(*self._treeview.get_children())
            except Exception:
                pass

            start = (self._current_page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_rows = self._fa_data[start:end]

            if not page_rows:
                # Empty state (D6). Show the appropriate message
                # based on WHY the free-agent pool is empty.
                empty_msg = self._empty_state_message()
                self._empty_label.configure(text=empty_msg)
                self._empty_label.pack(
                    expand=True, fill="both", padx=20, pady=40,
                    in_=self._treeview.master,
                )
                return

            try:
                self._empty_label.pack_forget()
            except Exception:
                pass

            # Alternate row colors for readability.
            try:
                self._treeview.tag_configure(
                    "even", background=get_theme().colors.bg_surface)
                self._treeview.tag_configure(
                    "odd", background=get_theme().colors.bg_surface_elevated)
            except Exception:
                pass

            for i, fighter in enumerate(page_rows):
                phase_phrase = _phrase_or_fallback(
                    fighter["career_phase_stored"], "(uncached)")
                momentum_phrase = _phrase_or_fallback(
                    fighter["momentum_stored"], "(uncached)")
                # Potential phrase. Per D1: reads from
                # fighter_descriptors.potential_desc (the interpretation-
                # layer projection of the raw potential number). NULL
                # across the seeded DB at schema 3.12.0 — fall back to
                # a sensible voice phrase that explains WHY the player
                # can't see a potential: they haven't scouted this
                # fighter yet. (Per the Soul doc, this information
                # asymmetry is the intended design.)
                potential_phrase = _phrase_or_fallback(
                    fighter["potential_stored"],
                    "(no scouting report yet)")
                record_str = _format_record(
                    fighter["record_wins"],
                    fighter["record_losses"],
                    fighter["record_draws"],
                )

                tag = "even" if i % 2 == 0 else "odd"
                self._treeview.insert(
                    "", "end",
                    iid=str(fighter["fighter_id"]),
                    values=(
                        fighter["name"],
                        fighter["weight_class_name"],
                        phase_phrase,
                        potential_phrase,
                        record_str,
                        momentum_phrase,
                    ),
                    tags=(tag,),
                )
        except Exception as e:
            print(f"Warning: free-agent table render failed: {e}",
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
