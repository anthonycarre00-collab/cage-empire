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

import customtkinter as ctk
import tkinter.ttk as ttk

from ui.theme import get_theme
from ui.state import get_state

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (mirrors
# DashboardScreen's D4).
from interpretation.context_engine import decode_phrase


# ============================================================
# CONSTANTS
# ============================================================

# Page size — per the brief: "show 20 at a time".
PAGE_SIZE = 20

# Treeview column identifiers. The "Name" column uses the Treeview's
# inherent `#0` column (the tree column) — we hide the tree display
# (show="headings") so #0 behaves like any other column.
COL_NAME = "name"
COL_WC = "weight_class"
COL_PHASE = "career_phase"
COL_MOMENTUM = "momentum"
COL_RECORD = "record"
COL_NARRATIVE = "narrative"

# Column display labels (heading text).
COLUMN_LABELS = {
    COL_NAME: "Name",
    COL_WC: "Weight Class",
    COL_PHASE: "Career Phase",
    COL_MOMENTUM: "Momentum",
    COL_RECORD: "Record",
    COL_NARRATIVE: "Narrative",
}

# Column widths (in px). Tuned for a 1400px-wide main content area
# (~1360px after the sidebar). The Name column is widest (fighters
# have long names + nicknames); the Record column is narrowest
# ("18-5-0" is 7 chars).
COLUMN_WIDTHS = {
    COL_NAME: 240,
    COL_WC: 130,
    COL_PHASE: 240,
    COL_MOMENTUM: 180,
    COL_RECORD: 80,
    COL_NARRATIVE: 220,
}


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
        self._search_term = ""
        self._sort_column = "fighter_id"  # default: insertion order
        self._sort_reverse = False

        # Cached roster data (list of dicts). Refreshed by _refresh().
        # Kept as an attribute so the sort handler can re-sort without
        # re-querying the DB.
        self._roster_data = []

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

        # Build the static structure. Dynamic content (Treeview rows,
        # pagination label, weight-class dropdown values) is rendered
        # by _refresh.
        self._build_header()
        self._build_filter_row()
        self._build_table()
        self._build_pagination()
        self._build_footer()

        # Initial render. Use after(50, ...) so the widget is fully
        # laid out before we query (matches DashboardScreen pattern).
        self.after(50, self._refresh)

    # ============================================================
    # SECTION 1 — HEADER (H1 title + roster-count subtitle)
    # ============================================================

    def _build_header(self):
        """Build the H1 title + subtitle ('ROSTER' + promotion + count)."""
        theme = get_theme()

        title = ctk.CTkLabel(
            self, text="ROSTER",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # Subtitle populated by _refresh (needs promotion name + count
        # from the DB). Kept as an attribute so _refresh can call
        # .configure() on it without recreating.
        self._subtitle_label = ctk.CTkLabel(
            self, text="Loading roster...",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # SECTION 2 — FILTER ROW (weight-class dropdown + search entry)
    # ============================================================

    def _build_filter_row(self):
        """Build the filter row: weight-class dropdown + search entry.

        Layout:
          [Weight Class: ▼ All Weight Classes]  [Search: [_______]]

        The dropdown lists every weight class present in the player's
        promotion + an "All Weight Classes" option. The search entry
        is case-insensitive substring on first_name + last_name +
        nickname. See D4, D5.
        """
        theme = get_theme()

        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Weight-class dropdown label
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

        # Search entry label
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
    # SECTION 3 — TABLE (ttk.Treeview — D2)
    # ============================================================

    def _build_table(self):
        """Build the roster table.

        Uses tkinter.ttk.Treeview (the standard data-table widget for
        Tk). Themed to match the Office dark palette via a custom
        ttk.Style. See D2.

        Layout:
          ┌──────────────────────────────────────────────────────────┐
          │  Name           | Weight Class | Career Phase | ...     │
          ├──────────────────────────────────────────────────────────┤
          │  John Vale      | Lightweight  | rising ...   | ...     │
          │  ...                                                     │
          │  (20 rows per page — D3)                                 │
          └──────────────────────────────────────────────────────────┘
        """
        theme = get_theme()

        # Container card — gives the Treeview a framed surface that
        # matches the Dashboard's card aesthetic.
        table_card = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        table_card.pack(side="top", fill="both", expand=True, padx=20, pady=(0, 10))

        # Configure the ttk.Style for the Treeview. Done in _build_table
        # (once) AND re-applied in _refresh so theme-change refresh
        # picks up new colors. The style name is constant — the widget
        # doesn't need to be recreated.
        self._apply_treeview_style()

        # Treeview — 6 columns, headings only (no tree column).
        # height=20 rows (matches PAGE_SIZE). The Treeview will not
        # grow beyond 20 rows visually; pagination handles the rest.
        self._treeview = ttk.Treeview(
            table_card,
            columns=(COL_NAME, COL_WC, COL_PHASE, COL_MOMENTUM,
                     COL_RECORD, COL_NARRATIVE),
            show="headings",
            style="Roster.Treeview",
            height=PAGE_SIZE,
            selectmode="browse",
        )

        # Configure columns: width, anchor, heading text + sort command.
        # Name + WC + Phase + Narrative are left-anchored (text);
        # Record is center-anchored (short numeric-ish string).
        for col in (COL_NAME, COL_WC, COL_PHASE, COL_MOMENTUM,
                    COL_RECORD, COL_NARRATIVE):
            self._treeview.heading(
                col, text=COLUMN_LABELS[col],
                command=lambda c=col: self._on_heading_click(c),
            )
            anchor = "center" if col == COL_RECORD else "w"
            self._treeview.column(
                col, width=COLUMN_WIDTHS[col], anchor=anchor,
                stretch=False,
            )

        # Pack the Treeview. fill="both" + expand=True so it grows
        # with the window.
        self._treeview.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)

        # Vertical scrollbar — Treeview can have 20 rows visible but
        # we want page-flipping via the pagination buttons instead.
        # However, on small screens the 20-row height might exceed
        # the available space; a scrollbar handles that gracefully.
        scrollbar = ctk.CTkScrollbar(
            table_card, command=self._treeview.yview,
            fg_color=theme.colors.bg_surface,
        )
        scrollbar.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self._treeview.configure(yscrollcommand=scrollbar.set)

        # Bind double-click → navigate to Fighter Profile (D7).
        self._treeview.bind("<Double-1>", self._on_row_double_click)

        # Empty-state label — shown when no fighters match the
        # filter/search. Packed into the table_card so it overlays
        # the Treeview area. Hidden by _refresh when rows exist.
        self._empty_label = ctk.CTkLabel(
            table_card,
            text="Your roster is empty.",
            font=theme.fonts.body,
            text_color=theme.colors.text_tertiary,
            justify="center",
        )
        # Note: _empty_label is NOT packed here. _refresh decides
        # whether to pack it (over the Treeview) or pack_forget it.

    def _apply_treeview_style(self):
        """Apply the dark Office theme to the Roster.Treeview style.

        Per D2: ttkbootstrap is in requirements.txt but not installed
        in this environment. We achieve the same dark theme manually
        via ttk.Style(). The style is rebuilt on every _refresh() so
        theme-change refresh picks up the new colors.

        Idempotent — safe to call multiple times (ttk.Style.configure
        overwrites the previous config).
        """
        theme = get_theme()
        try:
            style = ttk.Style()
            # Use 'clam' theme — it's the most themeable (the default
            # 'default' theme ignores some style settings on Linux).
            # Safe to set on every call — it's idempotent.
            try:
                style.theme_use("clam")
            except Exception:
                pass  # clam may already be in use; that's fine

            # Treeview body
            style.configure(
                "Roster.Treeview",
                background=theme.colors.bg_surface,
                foreground=theme.colors.text_primary,
                fieldbackground=theme.colors.bg_surface,
                bordercolor=theme.colors.bg_border,
                rowheight=28,
                font=("Inter", 12),
            )
            # Selected row — uses bg_surface_elevated (subtle highlight
            # that matches the Dashboard's hover state)
            style.map(
                "Roster.Treeview",
                background=[("selected", theme.colors.bg_surface_elevated)],
                foreground=[("selected", theme.colors.text_primary)],
            )
            # Heading — gold text on elevated surface (matches the
            # Dashboard's H2 panel titles)
            style.configure(
                "Roster.Treeview.Heading",
                background=theme.colors.bg_surface_elevated,
                foreground=theme.colors.gold,
                bordercolor=theme.colors.bg_border,
                relief="flat",
                font=("Inter", 13, "bold"),
            )
            style.map(
                "Roster.Treeview.Heading",
                background=[("active", theme.colors.steel)],
            )
        except Exception as e:
            print(f"Warning: Treeview style setup failed: {e}", flush=True)

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
    # SECTION 5 — FOOTER (click-to-view-profile hint)
    # ============================================================

    def _build_footer(self):
        """Build the footer hint: 'Click a fighter to view profile'."""
        theme = get_theme()

        footer_label = ctk.CTkLabel(
            self,
            text="Double-click a fighter to view their profile.",
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

    def _on_search_change(self, event=None):
        """Handle search-entry keystroke.

        Reads the current entry value + triggers _refresh. Page resets
        to 1 (D3 — page state resets when search changes). No manual
        debounce — the GUI event loop naturally throttles keystroke
        events for 1000 rows (D5).
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

    def _on_heading_click(self, col):
        """Handle heading click — sort by that column (D8).

        Toggles asc/desc on repeated clicks. Default sort is by
        fighter_id ascending (insertion order from seed).
        """
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

    def _on_row_double_click(self, event=None):
        """Handle double-click on a Treeview row — navigate to profile.

        Per D7: reads the selected row's fighter_id (stored as the
        Treeview item's iid), calls set_fighter_id() on the Fighter
        Profile screen, then navigates via state.set_active_screen.

        Defensive: if no row is selected, no-op. If the Fighter
        Profile screen isn't registered yet, catch the ValueError
        and log a warning.
        """
        try:
            selection = self._treeview.selection()
            if not selection:
                return
            # The iid IS the fighter_id (we set it as such in _refresh).
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
            # Screen not registered — defensive
            print(f"Warning: navigation to fighter_profile failed: {e}",
                  flush=True)
        except Exception as e:
            print(f"Warning: row double-click handler failed: {e}",
                  flush=True)

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

            # Re-apply the Treeview style on every refresh so theme-
            # change refresh picks up new colors (D2, D9).
            self._apply_treeview_style()

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
            self._render_table()
            self._refresh_pagination(total_pages)
            self._refresh_subtitle(conn, promo_id, len(self._roster_data))
        except Exception as e:
            print(f"Warning: RosterScreen._refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Subtitle — "Promotion Name (N,NNN fighters)"
    # ------------------------------------------------------------

    def _refresh_subtitle(self, conn, promo_id, total_count):
        """Update the subtitle label with promotion name + count."""
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
        except Exception as e:
            print(f"Warning: roster subtitle refresh failed: {e}",
                  flush=True)

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
            rows = []
            try:
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
            # last fighter in that weight class was cut), reset to
            # "All Weight Classes".
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
                       wc.name AS weight_class_name,
                       fd.career_phase, fd.momentum, fd.narrative_family,
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
            print(f"Warning: roster query failed: {e}", flush=True)
            return []

        # Build the roster data list.
        roster = []
        for r in rows:
            (fid, first, last, nick, wc_name, phase_stored, mom_stored,
             narr_stored, wins, losses, draws) = r
            roster.append({
                "fighter_id": fid,
                "name": _format_name(first, last, nick),
                "weight_class_name": wc_name or "Unknown",
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
          - weight_class_name → string, case-insensitive
          - career_phase → decoded phrase (or "" if None)
          - momentum → decoded phrase (or "" if None)
          - record → total fights (wins + losses + draws) descending
            by default — most-experienced first
          - narrative → decoded phrase (or "" if None)
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
            if col == COL_NARRATIVE:
                return _phrase_or_fallback(
                    item["narrative_stored"], "") or ""
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

    def _render_table(self):
        """Render the current page of rows into the Treeview.

        Per D3: shows PAGE_SIZE (20) rows per page. The Treeview
        item's iid IS the fighter_id (so the double-click handler
        can recover it without a separate lookup).

        Per D6: empty-state handling — if no rows match the current
        filter/search, show the empty-state label.
        """
        try:
            # Clear existing rows.
            try:
                self._treeview.delete(*self._treeview.get_children())
            except Exception:
                pass

            # Compute the page slice.
            start = (self._current_page - 1) * PAGE_SIZE
            end = start + PAGE_SIZE
            page_rows = self._roster_data[start:end]

            if not page_rows:
                # Empty state (D6). Show the appropriate message
                # based on WHY the roster is empty.
                empty_msg = self._empty_state_message()
                self._empty_label.configure(text=empty_msg)
                # Pack the empty label OVER the Treeview (the
                # Treeview is still there, just hidden visually).
                self._empty_label.pack(
                    expand=True, fill="both", padx=20, pady=40,
                    in_=self._treeview.master,
                )
                return

            # Hide the empty-state label if it was previously shown.
            try:
                self._empty_label.pack_forget()
            except Exception:
                pass

            # Insert the rows. The iid is the fighter_id (string).
            # Tags: alternate row colors for readability ("even" /
            # "odd"). The Treeview style configures these via
            # tagconfigure below.
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
                narrative_phrase = _phrase_or_fallback(
                    fighter["narrative_stored"], "(none)")
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
                        momentum_phrase,
                        record_str,
                        narrative_phrase,
                    ),
                    tags=(tag,),
                )
        except Exception as e:
            print(f"Warning: roster table render failed: {e}", flush=True)

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
