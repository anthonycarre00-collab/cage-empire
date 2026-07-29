"""CAGE EMPIRE — Dashboard screen (Stage 6 — Task 6.3).

The player's home screen — the FIRST real screen in CAGE EMPIRE
(every prior screen is a placeholder). Sets the pattern for all
subsequent Office Mode screens.

Shows:
  1. Top Story + Other Headlines (today's narrative)
  2. Promotion Status (cash, reputation, fan trust, roster, champions)
  3. Fighter Watch (Top Prospect / Hottest Streak / Biggest Fall)
  4. Recent News (the news_items feed)
  5. Quick-action buttons (Schedule Event / View Roster / Free Agents)

Per docs/GUI_PLAN.md §5.1: "What's happening now" — today's date,
key alerts, finance snapshot, recent news, next event card.

Per docs/CONVENTIONS.md §17 (UI Snapshot Rule — CRITICAL):
  Office Mode UI screens MUST read from `*_descriptors` and
  `daily_headlines` cache tables only. Direct reads of simulation
  tables (fighter_attributes, fighter_personality, fighter_career,
  contracts, etc.) are a §14-class violation.

  This screen reads from:
    - daily_headlines (cache — top story, other headlines, fighter
      watch subjects via fighter_id) — §17.3 cache table.
    - fighter_descriptors (cache — momentum + narrative_family
      voice phrases for Fighter Watch) — §17.3 cache table.
    - promotions (game state — cash, reputation, fan_trust. NOT a
      fighter attribute table. Per the Task 6.3 brief + §14, this
      is game-state data, not fighter data. The player needs to
      see their cash on the home screen.)
    - titles + weight_classes + fighters (game state — champion
      names. Names are NOT raw attribute values per §14.)
    - fighters (game state — first_name/last_name for champion +
      roster count. Count is game state, not a fighter attribute.)
    - news_items (game state — the news feed. Per Task 6.3 brief:
      "news_items is OK for display since it doesn't expose raw
      attribute values." Listed in §17.3 as a simulation table
      but the news feed is a fundamental game feature, not fighter
      data. Used here ONLY for the headline/topic/published_at
      fields — never for fighter attribute values.)

  This screen NEVER reads from:
    - fighter_attributes (raw 0-100 values)
    - fighter_personality (raw trait values)
    - fighter_career (raw potential, career_health numbers)

Per docs/CONVENTIONS.md §14 (Interpretation Layer):
  No raw attribute values appear in the player-facing UI.
    - Cash displays as "$50.0M" (game-state money, formatted).
    - Reputation displays as "Highly Respected" (voice band), NOT
      the raw 0-100 integer (e.g., 85).
    - Fan trust displays as "Strong" (voice band), NOT raw 75.
    - Roster count is a game-state integer — OK to display as
      "1,002 fighters" (it is NOT a fighter attribute).
    - Champion count is a game-state integer — OK.
    - Fighter Watch voice phrases come from fighter_descriptors
      (already voice-banded by the interpretation layer).

  The reputation/fan_trust band translation lives HERE as a local
  shim because the interpretation layer hasn't fully populated
  promotion_descriptors yet (the table exists per §17.3 but is
  empty in the current world DB). When Task 6.x lands the
  promotion_descriptors writer, this screen can switch to reading
  the voice phrases from there. Until then, the local bands
  enforce §14 (no raw numbers displayed). See D2 below.

Per docs/CONVENTIONS.md §15 (Event Bus):
  The screen does NOT publish events. The Advance Day button is
  in the top bar (src/ui/app.py); it calls services.clock.advance_
  day + state.refresh_all(). The Dashboard's _refresh() is called
  by GameState as part of refresh_all() — every screen re-queries
  + re-renders.

Architecture (mirrors SaveLoadScreen):
  - DashboardScreen(ctk.CTkFrame) — the screen widget.
  - _build_header() — H1 title + sim-date subtitle.
  - _build_top_row() — Top Story (left) | Promotion Status (right).
  - _build_fighter_watch() — 3 cards (Top Prospect / Hottest Streak
    / Biggest Fall).
  - _build_news_section() — scrollable recent-news list.
  - _build_actions() — Schedule Event / View Roster / Free Agents.
  - _refresh() — registered with GameState; re-queries every data
    source + re-renders. Safe to call repeatedly (destroys old
    dynamic widgets first, then renders new ones).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Source-of-truth map. See the §17 comment block above. The
      rule: fighter INTERPRETATION data (momentum, narrative
      family, career phase) comes from cache tables ONLY. Game-
      state data (cash, champions, roster count, news feed) comes
      from the simulation tables that hold it. The Dashboard never
      touches fighter_attributes / fighter_personality /
      fighter_career.
  D2  Local reputation/fan_trust voice bands. The interpretation
      layer has not yet populated promotion_descriptors (the table
      is empty in the current world DB). To honor §14 ("no raw
      attribute values in the player-facing UI") WITHOUT waiting
      for that population, the Dashboard applies its own voice
      bands to the raw 0-100 reputation + fan_trust columns. This
      is a transitional shim — when promotion_descriptors is
      populated by a future interpretation task, the Dashboard
      will switch to reading the voice phrases from there. The
      bands themselves mirror §14.3's threshold approach (banded
      descriptors that change only on band-boundary crossings).
      Bands (reputation): 90-95 Legendary / 75-89 Highly Respected
      / 60-74 Well Respected / 40-59 Established / 25-39
      Up-and-Coming / 10-24 Struggling. Bands (fan_trust):
      85+ Devoted / 70-84 Strong / 55-69 Loyal / 40-54 Wavering /
      25-39 Restless / 10-24 Alienated.
  D3  "Hottest Streak" card query. The other two Fighter Watch
      cards (Top Prospect / Biggest Fall) come straight from the
      daily_headlines rows (fastest_rising / biggest_fall). The
      Hottest Streak card queries fighter_descriptors directly for
      momentum='very_high' (or 'high' as fallback), EXCLUDING the
      fastest_rising fighter so the card shows a different face
      when possible. The voice phrase is decoded from the "label||
      phrase" storage format via interpretation.context_engine.
      decode_phrase (the canonical interpretation-layer helper).
  D4  Voice-phrase decoding. The fighter_descriptors cache columns
      store "canonical_label||voice_phrase" (per §17.4 + the
      interpretation engines' bulk-load pattern). The Dashboard
      uses interpretation.context_engine.decode_phrase to extract
      the player-facing voice phrase. This is the SAME helper the
      interpretation engines use — single source of truth, no
      duplicate parsing logic.
  D5  Scrollable root. The Dashboard's content can exceed the
      viewport (esp. on the Recent News list when news_items has
      many rows). The root container is a CTkScrollableFrame so
      the whole screen scrolls naturally. Cards inside keep their
      own bg_surface background so they read as discrete panels.
  D6  Empty-state handling. Every section degrades gracefully:
      - No daily_headlines → "A quiet day across the promotions."
      - No fighter with very_high/high momentum → "No one's on a
        hot streak right now."
      - No champions → "No champions yet — go win some belts."
      - No news_items → "The newswire is quiet."
      - No fighters in roster → "Your roster is empty."
      Defensive: a missing table or query error doesn't crash the
      screen — the section shows its empty-state + the warning is
      logged.
  D7  Action-button navigation. The three quick-action buttons
      call state.set_active_screen() to navigate. They target
      screens that are not yet implemented (event_builder, roster,
      free_agents) — those screens show the placeholder label via
      CageEmpireApp._navigate until their own tasks land. This is
      intentional: the Dashboard is the navigation hub, even when
      destinations are placeholders.
  D8  Refresh pattern. Following SaveLoadScreen: dynamic widgets
      are tracked in instance lists (_headline_widgets,
      _champion_widgets, _news_widgets, _watch_cards). _refresh()
      destroys them, re-queries, re-renders. Static structure
      (titles, action buttons, scrollable frames) is built once
      in __init__. Theme-change refresh (state.refresh_all after
      set_theme) re-renders with the new theme's colors/fonts.
  D9  Champion ordering. Champions are ordered by weight_class
      weight ascending (heavyweight first, strawweight last) —
      mirrors how fight sports display title hierarchies (the
      biggest weight class is the marquee). Joined through
      weight_classes.display_order which the seed scripts
      populate. Falls back to weight_class_id ordering if
      display_order is NULL.
"""

import sqlite3
from datetime import datetime

import customtkinter as ctk

from ui.theme import get_theme
from ui.state import get_state

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (D4).
from interpretation.context_engine import decode_phrase


# ============================================================
# CONSTANTS — headline type → display label
# ============================================================
# Maps daily_headlines.headline_type (the canonical label per
# CONVENTIONS §17.3 + headline_engine.HEADLINE_*) to the player-facing
# card title.

_HEADLINE_TYPE_TO_CARD_TITLE = {
    "top_story": "TOP STORY",
    "upset_of_week": "Upset of the Week",
    "fastest_rising": "Fastest Rising",
    "biggest_fall": "Biggest Fall",
}


# ============================================================
# LOCAL VOICE BANDS (D2 — transitional shim, removed when
# promotion_descriptors is populated by the interpretation layer)
# ============================================================

def _reputation_band(raw_value):
    """Translate a raw 0-100 reputation value to a voice phrase.

    Per §14: no raw attribute values in the player-facing UI. The
    bands mirror §14.3's threshold approach (changes only on band-
    boundary crossings, so the descriptor is stable across small
    fluctuations).

    Args:
        raw_value: int/float/str — the raw reputation column from
            promotions.reputation. Defensive — any unparseable
            value returns "Unknown".

    Returns:
        Voice phrase like "Highly Respected" — never the raw number.
    """
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        return "Unknown"
    if v >= 90:
        return "Legendary"
    if v >= 75:
        return "Highly Respected"
    if v >= 60:
        return "Well Respected"
    if v >= 40:
        return "Established"
    if v >= 25:
        return "Up-and-Coming"
    if v >= 10:
        return "Struggling"
    return "Unknown"


def _fan_trust_band(raw_value):
    """Translate a raw 0-100 fan_trust value to a voice phrase.

    Per §14: no raw attribute values in the player-facing UI.

    Args:
        raw_value: int/float/str — the raw fan_trust column from
            promotions.fan_trust. Defensive — any unparseable value
            returns "Unknown".

    Returns:
        Voice phrase like "Strong" — never the raw number.
    """
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        return "Unknown"
    if v >= 85:
        return "Devoted"
    if v >= 70:
        return "Strong"
    if v >= 55:
        return "Loyal"
    if v >= 40:
        return "Wavering"
    if v >= 25:
        return "Restless"
    if v >= 10:
        return "Alienated"
    return "Unknown"


# ============================================================
# HELPERS — formatting
# ============================================================

def _format_cash(cash):
    """Format a cash value as $X.XM / $XK / $X,XXX.

    Matches the top bar's _update_top_bar formatting (src/ui/app.py
    lines 333-338) + SaveLoadScreen._format_cash so the Dashboard
    displays cash consistently with the rest of the UI. This is
    game-state money, not a fighter attribute — OK per §14.
    """
    if cash is None:
        return "—"
    try:
        cash = float(cash)
    except (TypeError, ValueError):
        return "—"
    if abs(cash) >= 1_000_000:
        return f"${cash / 1_000_000:.1f}M"
    if abs(cash) >= 1_000:
        return f"${cash / 1_000:.0f}K"
    return f"${cash:,.0f}"


def _format_date(iso_date_str):
    """Format an ISO date string ('2026-12-23') for display.

    Returns '2026-12-23' unchanged on parse failure (defensive —
    news_items.published_at is a TEXT column the seed scripts write).
    """
    if not iso_date_str:
        return ""
    try:
        # Truncate to date portion (handles 'YYYY-MM-DD HH:MM:SS').
        s = str(iso_date_str)[:10]
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(iso_date_str)


def _topic_label(topic):
    """Render a news_items.topic as a bracketed display label.

    The seed scripts sometimes store 'milestone' with a leading
    space (' ilestone') — defensive strip + upper-case so the news
    feed reads cleanly.
    """
    if not topic:
        return "news"
    return str(topic).strip() or "news"


# ============================================================
# DASHBOARD SCREEN
# ============================================================

class DashboardScreen(ctk.CTkFrame):
    """Dashboard — the player's home screen.

    The first real screen in CAGE EMPIRE. Office Mode only (it is
    NOT a Fight Night screen). Registered with GameState as
    'dashboard'. The refresh callback (`_refresh`) re-queries every
    data source + re-renders.

    Usage:
        screen = DashboardScreen(parent_frame)
        state.register_screen("dashboard", screen, screen._refresh)
        state.set_active_screen("dashboard")
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Configure the screen's own background to match the Office
        # Mode base — cards inside sit on top of this.
        theme = get_theme()
        self.configure(fg_color=theme.colors.bg_base)

        # Dynamic-widget tracking. _refresh destroys these before
        # re-rendering. See D8.
        self._headline_widgets = []        # Top Story + Other Headlines rows
        self._champion_widgets = []        # Champion rows in Promotion Status
        self._promotion_status_widgets = []  # Cash/Rep/Trust/Roster/Champions rows
        self._watch_cards = []             # Three Fighter Watch cards
        self._news_widgets = []            # Recent News rows
        self._subtitle_label = None        # The "Week N, Year N · Promo" subtitle

        # Build the static structure (titles, scrollable containers,
        # action buttons). Dynamic content is rendered by _refresh.
        self._build_header()
        self._build_top_row()
        self._build_fighter_watch()
        self._build_news_section()
        self._build_actions()

        # Initial render. Use after(50, ...) so the widget is fully
        # laid out before we query (matches SaveLoadScreen pattern).
        # Safe — if the screen is destroyed before the callback fires,
        # _refresh's try/except handles it.
        self.after(50, self._refresh)

    # ============================================================
    # SECTION 1 — HEADER (H1 title + sim-date subtitle)
    # ============================================================

    def _build_header(self):
        """Build the H1 title + subtitle ('DASHBOARD' + sim-date)."""
        theme = get_theme()

        title = ctk.CTkLabel(
            self, text="DASHBOARD",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # Subtitle populated by _refresh (needs sim-date + promotion
        # name from the DB). Kept as an attribute so _refresh can
        # call .configure() on it without recreating.
        self._subtitle_label = ctk.CTkLabel(
            self, text="",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # SECTION 2 — TOP ROW (Top Story | Promotion Status)
    # ============================================================

    def _build_top_row(self):
        """Build the two-column top row.

        Layout:
          ┌──────────────────────────┬───────────────────────────────┐
          │  TOP STORY               │  PROMOTION STATUS             │
          │  [headline_text]         │  Cash: $50.0M                 │
          │  [body_text]             │  Reputation: Highly Respected │
          │                          │  Fan Trust: Strong            │
          │  ── OTHER HEADLINES ──   │  Roster: 1,002 fighters       │
          │  ▸ headline 2            │  Champions: 5                 │
          │  ▸ headline 3            │                               │
          │  ▸ headline 4            │  ── YOUR CHAMPIONS ──         │
          │                          │  Heavyweight: J. Cardoso      │
          │                          │  ...                          │
          └──────────────────────────┴───────────────────────────────┘
        """
        theme = get_theme()

        # Container — two columns with equal weight, gap via padx.
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="top", fill="x", padx=20, pady=(0, 15))
        row.grid_columnconfigure(0, weight=1, uniform="top")
        row.grid_columnconfigure(1, weight=1, uniform="top")

        # ---- LEFT: Top Story + Other Headlines ----
        self.top_story_card = ctk.CTkFrame(
            row, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        self.top_story_card.grid(row=0, column=0, sticky="nsew",
                                  padx=(0, 8))

        # Card title (gold H2)
        ts_title = ctk.CTkLabel(
            self.top_story_card, text="TOP STORY",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        ts_title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        # Container for the top-story content (headline + body).
        # Populated by _refresh.
        self.top_story_content = ctk.CTkFrame(
            self.top_story_card, fg_color="transparent",
        )
        self.top_story_content.pack(side="top", fill="x", padx=15, pady=(0, 5))

        # "OTHER HEADLINES" sub-title
        oh_title = ctk.CTkLabel(
            self.top_story_card, text="── OTHER HEADLINES ──",
            font=theme.fonts.h3, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        oh_title.pack(side="top", fill="x", padx=15, pady=(10, 5))

        # Container for the other-headlines list. Populated by _refresh.
        self.other_headlines_content = ctk.CTkFrame(
            self.top_story_card, fg_color="transparent",
        )
        self.other_headlines_content.pack(
            side="top", fill="x", padx=15, pady=(0, 12))

        # ---- RIGHT: Promotion Status + Your Champions ----
        self.promo_card = ctk.CTkFrame(
            row, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        self.promo_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ps_title = ctk.CTkLabel(
            self.promo_card, text="PROMOTION STATUS",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        ps_title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        # Container for the status rows (cash/rep/trust/roster/champions).
        self.promo_status_content = ctk.CTkFrame(
            self.promo_card, fg_color="transparent",
        )
        self.promo_status_content.pack(
            side="top", fill="x", padx=15, pady=(0, 5))

        # "YOUR CHAMPIONS" sub-title
        yc_title = ctk.CTkLabel(
            self.promo_card, text="── YOUR CHAMPIONS ──",
            font=theme.fonts.h3, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        yc_title.pack(side="top", fill="x", padx=15, pady=(10, 5))

        # Container for the champion rows. Populated by _refresh.
        self.champions_content = ctk.CTkFrame(
            self.promo_card, fg_color="transparent",
        )
        self.champions_content.pack(
            side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 3 — FIGHTER WATCH (3 cards)
    # ============================================================

    def _build_fighter_watch(self):
        """Build the Fighter Watch section: 3 cards in a row.

        Layout:
          ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
          │ TOP PROSPECT    │ │ HOTTEST STREAK  │ │ BIGGEST FALL    │
          │ [name]          │ │ [name]          │ │ [name]          │
          │ [voice phrase]  │ │ [voice phrase]  │ │ [voice phrase]  │
          └─────────────────┘ └─────────────────┘ └─────────────────┘
        """
        theme = get_theme()

        # Section title (full-width)
        fw_section_title = ctk.CTkLabel(
            self, text="FIGHTER WATCH",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        fw_section_title.pack(side="top", fill="x", padx=20, pady=(0, 5))

        # Three-column container
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="top", fill="x", padx=20, pady=(0, 15))
        row.grid_columnconfigure(0, weight=1, uniform="watch")
        row.grid_columnconfigure(1, weight=1, uniform="watch")
        row.grid_columnconfigure(2, weight=1, uniform="watch")

        # Card containers — kept as attributes so _refresh can populate
        # them (and so theme-change refresh picks up the new colors).
        self.watch_card_top = ctk.CTkFrame(
            row, fg_color=theme.colors.bg_surface, corner_radius=8)
        self.watch_card_top.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.watch_card_streak = ctk.CTkFrame(
            row, fg_color=theme.colors.bg_surface, corner_radius=8)
        self.watch_card_streak.grid(row=0, column=1, sticky="nsew", padx=3)

        self.watch_card_fall = ctk.CTkFrame(
            row, fg_color=theme.colors.bg_surface, corner_radius=8)
        self.watch_card_fall.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

    # ============================================================
    # SECTION 4 — RECENT NEWS (scrollable list)
    # ============================================================

    def _build_news_section(self):
        """Build the Recent News section with a scrollable list.

        Layout:
          ┌─────────────────────────────────────────────────────────┐
          │  RECENT NEWS                                            │
          │  ┌───────────────────────────────────────────────────┐  │
          │  │ [debut] Pawel Krawczyk makes professional debut  │  │
          │  │         · 2026-12-23                              │  │
          │  │ [upset] Jerry Roberts stuns John Rodriguez...    │  │
          │  │         · 2026-11-27                              │  │
          │  │ ...                                               │  │
          │  └───────────────────────────────────────────────────┘  │
          └─────────────────────────────────────────────────────────┘

        The list is rendered by _refresh() (called once on init via
        after(50, ...) and again whenever the screen is shown).
        """
        theme = get_theme()

        news_section_title = ctk.CTkLabel(
            self, text="RECENT NEWS",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        news_section_title.pack(side="top", fill="x", padx=20, pady=(0, 5))

        # Fixed-height scrollable frame so the list scrolls within the
        # visible area rather than growing the screen indefinitely
        # (per the UI rules: max height with scroll overflow).
        self.news_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.colors.bg_surface,
            corner_radius=8,
            height=200,
        )
        self.news_scroll.pack(side="top", fill="x", padx=20, pady=(0, 15))

        # Empty-state label — shown when there's no news. Kept as an
        # attribute so _refresh can show/hide it.
        self.news_empty_label = ctk.CTkLabel(
            self.news_scroll,
            text="The newswire is quiet.",
            font=theme.fonts.body,
            text_color=theme.colors.text_tertiary,
            justify="center",
        )
        self.news_empty_label.pack(fill="x", padx=20, pady=30)

    # ============================================================
    # SECTION 5 — ACTIONS (Schedule Event / View Roster / Free Agents)
    # ============================================================

    def _build_actions(self):
        """Build the quick-action button row at the bottom.

        Per D7: these navigate via state.set_active_screen(). Target
        screens may be placeholders until their own tasks land — that
        is intentional. The Dashboard is the navigation hub.
        """
        theme = get_theme()

        actions_row = ctk.CTkFrame(self, fg_color="transparent")
        actions_row.pack(side="top", fill="x", padx=20, pady=(0, 15))

        # Schedule Event — gold accent (primary action).
        schedule_btn = ctk.CTkButton(
            actions_row, text="+ Schedule Event",
            font=theme.fonts.h3,
            width=160, height=34,
            corner_radius=6,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            command=self._on_schedule_event,
        )
        schedule_btn.pack(side="left", padx=(0, 10))

        # View Roster — neutral elevated surface.
        roster_btn = ctk.CTkButton(
            actions_row, text="View Roster",
            font=theme.fonts.h3,
            width=140, height=34,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_view_roster,
        )
        roster_btn.pack(side="left", padx=(0, 10))

        # View Free Agents — neutral elevated surface.
        free_agents_btn = ctk.CTkButton(
            actions_row, text="View Free Agents",
            font=theme.fonts.h3,
            width=160, height=34,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_view_free_agents,
        )
        free_agents_btn.pack(side="left")

    # ============================================================
    # HANDLERS — navigation (D7)
    # ============================================================

    def _on_schedule_event(self):
        """Navigate to the Event Builder screen."""
        try:
            get_state().set_active_screen("event_builder")
        except (ValueError, Exception) as e:
            print(f"Warning: navigation to event_builder failed: {e}",
                  flush=True)

    def _on_view_roster(self):
        """Navigate to the Roster screen."""
        try:
            get_state().set_active_screen("roster")
        except (ValueError, Exception) as e:
            print(f"Warning: navigation to roster failed: {e}",
                  flush=True)

    def _on_view_free_agents(self):
        """Navigate to the Free Agents screen."""
        try:
            get_state().set_active_screen("free_agents")
        except (ValueError, Exception) as e:
            print(f"Warning: navigation to free_agents failed: {e}",
                  flush=True)

    # ============================================================
    # REFRESH CALLBACK (registered with GameState)
    # ============================================================

    def _refresh(self):
        """Refresh callback — re-query every data source + re-render.

        Registered with GameState as this screen's refresh callback.
        Called:
          - Once on init (via after(50, ...)).
          - On every navigation to this screen (set_active_screen
            triggers state.refresh(name)).
          - On refresh_all() (after Advance Day, Save, Load, theme
            toggle).
          - When the player clicks the Refresh button (if added).

        Safe to call repeatedly — destroys the old dynamic widgets
        before rendering the new ones. Defensive against DB errors
        (if a query throws, the section shows its empty-state).
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                return
            promo_id = state.get_player_promotion_id()

            # Refresh each section in its own try/except so a single
            # failure doesn't abort the others (D6 — empty-state).
            self._refresh_subtitle(conn, promo_id)
            self._refresh_top_story(conn)
            self._refresh_promotion_status(conn, promo_id)
            self._refresh_champions(conn, promo_id)
            self._refresh_fighter_watch(conn)
            self._refresh_news(conn)
        except Exception as e:
            print(f"Warning: DashboardScreen._refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Subtitle — "Week N, Year N · Promotion Name"
    # ------------------------------------------------------------

    def _refresh_subtitle(self, conn, promo_id):
        """Update the subtitle label with sim-date + promotion name."""
        try:
            theme = get_theme()
            # Sim date from the clock
            week = "?"
            year = "?"
            try:
                clock_row = conn.execute(
                    "SELECT current_week, current_year "
                    "FROM simulation_clock WHERE clock_id=1"
                ).fetchone()
                if clock_row:
                    week = clock_row[0] if clock_row[0] is not None else "?"
                    year = clock_row[1] if clock_row[1] is not None else "?"
            except sqlite3.Error:
                pass

            # Promotion name
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

            text = f"Week {week}, Year {year}  ·  {promo_name}"
            self._subtitle_label.configure(
                text=text,
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )
        except Exception as e:
            print(f"Warning: subtitle refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Top Story + Other Headlines (daily_headlines cache — §17)
    # ------------------------------------------------------------

    def _refresh_top_story(self, conn):
        """Render the Top Story card + the Other Headlines list.

        Reads from daily_headlines (per §17 — this is a cache table,
        the interpretation layer is the only writer). The top_story
        row populates the TOP STORY card; the other 3 types populate
        the OTHER HEADLINES list.
        """
        try:
            theme = get_theme()

            # Destroy old dynamic widgets (D8).
            for w in self._headline_widgets:
                try:
                    w.destroy()
                except Exception:
                    pass
            self._headline_widgets = []

            # Query all headlines for the latest headline_date. We
            # don't filter by date here — the daily pass writes 4 rows
            # per day with INSERT OR REPLACE, so the latest set is
            # always the most recent. ORDER BY headline_type so the
            # display order is deterministic.
            rows = []
            try:
                rows = conn.execute(
                    "SELECT headline_type, headline_text, body_text, fighter_id "
                    "FROM daily_headlines "
                    "ORDER BY headline_date DESC, headline_type ASC"
                ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: daily_headlines query failed: {e}",
                      flush=True)

            # De-duplicate by headline_type (in case multiple dates
            # exist — take the first occurrence of each type from the
            # latest date set).
            seen_types = set()
            headlines = []
            for r in rows:
                htype = r[0]
                if htype in seen_types:
                    continue
                seen_types.add(htype)
                headlines.append({
                    "type": htype,
                    "text": r[1] or "",
                    "body": r[2] or "",
                    "fighter_id": r[3],
                })

            # Separate top_story from the rest.
            top_story = next(
                (h for h in headlines if h["type"] == "top_story"), None)
            others = [h for h in headlines if h["type"] != "top_story"]

            # ---- TOP STORY card content ----
            if top_story:
                # Headline text (large, primary color)
                head_label = ctk.CTkLabel(
                    self.top_story_content,
                    text=top_story["text"] or "Today's top story",
                    font=theme.fonts.h2,
                    text_color=theme.colors.text_primary,
                    anchor="w", wraplength=380, justify="left",
                )
                head_label.pack(side="top", fill="x", pady=(0, 5))
                self._headline_widgets.append(head_label)

                # Body text (smaller, secondary color)
                if top_story["body"]:
                    body_label = ctk.CTkLabel(
                        self.top_story_content,
                        text=top_story["body"],
                        font=theme.fonts.body,
                        text_color=theme.colors.text_secondary,
                        anchor="w", wraplength=380, justify="left",
                    )
                    body_label.pack(side="top", fill="x")
                    self._headline_widgets.append(body_label)
            else:
                # Empty state (D6)
                empty_label = ctk.CTkLabel(
                    self.top_story_content,
                    text="A quiet day across the promotions.",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    anchor="w", wraplength=380, justify="left",
                )
                empty_label.pack(side="top", fill="x")
                self._headline_widgets.append(empty_label)

            # ---- OTHER HEADLINES list ----
            if not others:
                empty_label = ctk.CTkLabel(
                    self.other_headlines_content,
                    text="No other headlines today.",
                    font=theme.fonts.body_small,
                    text_color=theme.colors.text_tertiary,
                    anchor="w",
                )
                empty_label.pack(side="top", fill="x")
                self._headline_widgets.append(empty_label)
            else:
                for h in others:
                    # Card title (e.g., "Upset of the Week") — small caption
                    card_title = _HEADLINE_TYPE_TO_CARD_TITLE.get(
                        h["type"], h["type"].replace("_", " ").title())
                    title_label = ctk.CTkLabel(
                        self.other_headlines_content,
                        text=card_title,
                        font=theme.fonts.caption,
                        text_color=theme.colors.gold,
                        anchor="w",
                    )
                    title_label.pack(side="top", fill="x", pady=(5, 0))
                    self._headline_widgets.append(title_label)

                    # Headline text — with a ▸ marker
                    text_label = ctk.CTkLabel(
                        self.other_headlines_content,
                        text=f"▸ {h['text']}",
                        font=theme.fonts.body,
                        text_color=theme.colors.text_primary,
                        anchor="w", wraplength=380, justify="left",
                    )
                    text_label.pack(side="top", fill="x")
                    self._headline_widgets.append(text_label)
        except Exception as e:
            print(f"Warning: top-story refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Promotion Status (promotions + fighters — game state, §14 OK)
    # ------------------------------------------------------------

    def _refresh_promotion_status(self, conn, promo_id):
        """Render the Promotion Status rows (cash/rep/trust/roster/count).

        Per D1: reads from promotions (game state — cash, reputation,
        fan_trust) + fighters (roster count — game state). Per D2:
        reputation + fan_trust pass through local voice bands before
        display.
        """
        try:
            theme = get_theme()

            # Destroy old dynamic widgets (D8).
            for w in self._promotion_status_widgets:
                try:
                    w.destroy()
                except Exception:
                    pass
            self._promotion_status_widgets = []

            # Query the player's promotion.
            cash = None
            reputation_raw = None
            fan_trust_raw = None
            try:
                promo_row = conn.execute(
                    "SELECT current_cash, reputation, fan_trust "
                    "FROM promotions WHERE promotion_id=?",
                    (promo_id,),
                ).fetchone()
                if promo_row:
                    cash = promo_row[0]
                    reputation_raw = promo_row[1]
                    fan_trust_raw = promo_row[2]
            except sqlite3.Error as e:
                print(f"Warning: promotions query failed: {e}",
                      flush=True)

            # Query roster count (game state, OK per §14 — it's a count,
            # not a fighter attribute).
            roster_count = 0
            try:
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM fighters "
                    "WHERE current_promotion_id=? AND is_active=1",
                    (promo_id,),
                ).fetchone()
                if count_row:
                    roster_count = count_row[0]
            except sqlite3.Error as e:
                print(f"Warning: roster count query failed: {e}",
                      flush=True)

            # Query champion count (game state).
            champion_count = 0
            try:
                champ_row = conn.execute(
                    "SELECT COUNT(*) FROM titles "
                    "WHERE promotion_id=? AND is_vacant=0 "
                    "AND current_champion_fighter_id IS NOT NULL",
                    (promo_id,),
                ).fetchone()
                if champ_row:
                    champion_count = champ_row[0]
            except sqlite3.Error as e:
                print(f"Warning: champion count query failed: {e}",
                      flush=True)

            # Voice-banded display values (D2 — §14 compliance).
            reputation_voice = _reputation_band(reputation_raw)
            fan_trust_voice = _fan_trust_band(fan_trust_raw)

            # Render the five status rows.
            rows = [
                ("Cash", _format_cash(cash), theme.colors.gold,
                 theme.fonts.mono),
                ("Reputation", reputation_voice,
                 theme.colors.text_primary, theme.fonts.body),
                ("Fan Trust", fan_trust_voice,
                 theme.colors.text_primary, theme.fonts.body),
                ("Roster", f"{roster_count:,} fighters",
                 theme.colors.text_primary, theme.fonts.body),
                ("Champions", f"{champion_count}",
                 theme.colors.text_primary, theme.fonts.body),
            ]

            for label, value, value_color, value_font in rows:
                row_frame = ctk.CTkFrame(
                    self.promo_status_content, fg_color="transparent")
                row_frame.pack(side="top", fill="x", pady=2)

                lbl = ctk.CTkLabel(
                    row_frame, text=f"{label}:",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_secondary,
                    anchor="w",
                )
                lbl.pack(side="left", padx=(0, 8))

                val = ctk.CTkLabel(
                    row_frame, text=value,
                    font=value_font,
                    text_color=value_color,
                    anchor="e",
                )
                val.pack(side="right")

                self._promotion_status_widgets.append(row_frame)
        except Exception as e:
            print(f"Warning: promotion-status refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Champions list (titles + weight_classes + fighters — game state)
    # ------------------------------------------------------------

    def _refresh_champions(self, conn, promo_id):
        """Render the YOUR CHAMPIONS list.

        Per D1: reads from titles + weight_classes + fighters (game
        state — champion names, NOT raw attribute values). Per D9:
        ordered by weight_class display_order (heavyweight first).
        """
        try:
            theme = get_theme()

            # Destroy old dynamic widgets (D8).
            for w in self._champion_widgets:
                try:
                    w.destroy()
                except Exception:
                    pass
            self._champion_widgets = []

            # Query champions — join titles → weight_classes → fighters.
            # display_order ascending (heavyweight first). Fall back to
            # weight_class_id if display_order is NULL.
            rows = []
            try:
                rows = conn.execute(
                    """
                    SELECT wc.name, f.first_name, f.last_name
                    FROM titles t
                    JOIN weight_classes wc
                      ON wc.weight_class_id = t.weight_class_id
                    LEFT JOIN fighters f
                      ON f.fighter_id = t.current_champion_fighter_id
                    WHERE t.promotion_id=? AND t.is_vacant=0
                      AND t.current_champion_fighter_id IS NOT NULL
                    ORDER BY COALESCE(wc.display_order, wc.weight_class_id)
                        ASC
                    """,
                    (promo_id,),
                ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: champions query failed: {e}",
                      flush=True)

            if not rows:
                empty_label = ctk.CTkLabel(
                    self.champions_content,
                    text="No champions yet — go win some belts.",
                    font=theme.fonts.body_small,
                    text_color=theme.colors.text_tertiary,
                    anchor="w",
                )
                empty_label.pack(side="top", fill="x")
                self._champion_widgets.append(empty_label)
                return

            for wc_name, first, last in rows:
                champion_name = f"{first or ''} {last or ''}".strip()
                row_frame = ctk.CTkFrame(
                    self.champions_content, fg_color="transparent")
                row_frame.pack(side="top", fill="x", pady=2)

                wc_label = ctk.CTkLabel(
                    row_frame, text=f"{wc_name or 'Unknown'}:",
                    font=theme.fonts.body,
                    text_color=theme.colors.gold,
                    anchor="w",
                )
                wc_label.pack(side="left", padx=(0, 8))

                name_label = ctk.CTkLabel(
                    row_frame,
                    text=(champion_name or "Vacant"),
                    font=theme.fonts.body,
                    text_color=theme.colors.text_primary,
                    anchor="e",
                )
                name_label.pack(side="right")

                self._champion_widgets.append(row_frame)
        except Exception as e:
            print(f"Warning: champions refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Fighter Watch (daily_headlines + fighter_descriptors — §17 cache)
    # ------------------------------------------------------------

    def _refresh_fighter_watch(self, conn):
        """Render the three Fighter Watch cards.

        Per D1+D3+D4:
          - Top Prospect: from daily_headlines.fastest_rising → fighter_id
            → fighter_descriptors.narrative_family voice phrase.
          - Hottest Streak: direct query of fighter_descriptors for
            momentum='very_high' (or 'high' fallback), EXCLUDING the
            Top Prospect fighter so the card shows a different face
            when possible. Voice phrase = decoded momentum phrase.
          - Biggest Fall: from daily_headlines.biggest_fall → fighter_id
            → fighter_descriptors.momentum voice phrase.

        Voice phrases decoded via interpretation.context_engine.
        decode_phrase (D4 — single source of truth for the "label||
        phrase" format).
        """
        try:
            theme = get_theme()

            # Destroy old dynamic widgets (D8).
            for w in self._watch_cards:
                try:
                    w.destroy()
                except Exception:
                    pass
            self._watch_cards = []

            # Pull the latest headlines for fighter_id lookups.
            fastest_rising = None
            biggest_fall = None
            try:
                hl_rows = conn.execute(
                    "SELECT headline_type, fighter_id "
                    "FROM daily_headlines "
                    "ORDER BY headline_date DESC, headline_type ASC"
                ).fetchall()
                seen = set()
                for htype, fid in hl_rows:
                    if htype in seen:
                        continue
                    seen.add(htype)
                    if htype == "fastest_rising" and fid:
                        fastest_rising = fid
                    elif htype == "biggest_fall" and fid:
                        biggest_fall = fid
            except sqlite3.Error as e:
                print(f"Warning: fighter-watch headline query failed: {e}",
                      flush=True)

            # ---- TOP PROSPECT card ----
            top_prospect_data = self._lookup_fighter_watch_data(
                conn, fastest_rising)
            self._render_watch_card(
                self.watch_card_top,
                "TOP PROSPECT",
                top_prospect_data,
                default_voice="the wunderkind everyone's talking about",
                empty_voice="No prospect emerging yet.",
            )

            # ---- HOTTEST STREAK card (D3 — exclude top-prospect fighter) ----
            streak_fighter_id = self._find_hottest_streak_fighter(
                conn, exclude_ids={fastest_rising} if fastest_rising else set())
            streak_data = self._lookup_fighter_watch_data(
                conn, streak_fighter_id)
            self._render_watch_card(
                self.watch_card_streak,
                "HOTTEST STREAK",
                streak_data,
                default_voice="riding a hot streak",
                empty_voice="No one's on a hot streak right now.",
            )

            # ---- BIGGEST FALL card ----
            biggest_fall_data = self._lookup_fighter_watch_data(
                conn, biggest_fall)
            self._render_watch_card(
                self.watch_card_fall,
                "BIGGEST FALL",
                biggest_fall_data,
                default_voice="in freefall",
                empty_voice="Nobody's sliding today.",
            )
        except Exception as e:
            print(f"Warning: fighter-watch refresh failed: {e}",
                  flush=True)

    def _lookup_fighter_watch_data(self, conn, fighter_id):
        """Look up a fighter's name + voice phrases for a watch card.

        Per D1+D4: reads from fighters (first_name/last_name only —
        NOT attributes) + fighter_descriptors (cache — momentum +
        narrative_family voice phrases). The "label||phrase" storage
        is decoded via decode_phrase (D4).

        Returns:
            dict with keys:
              name: "First Last" or "The fighter"
              momentum_phrase: voice phrase (e.g., "building serious
                momentum") or None
              narrative_phrase: voice phrase (e.g., "the wunderkind
                everyone's talking about") or None
            Returns None if fighter_id is None or lookup fails.
        """
        if fighter_id is None:
            return None
        try:
            row = conn.execute(
                """
                SELECT f.first_name, f.last_name,
                       fd.momentum, fd.narrative_family
                FROM fighters f
                LEFT JOIN fighter_descriptors fd
                  ON fd.fighter_id = f.fighter_id
                WHERE f.fighter_id=?
                """,
                (fighter_id,),
            ).fetchone()
            if not row:
                return None
            first, last, momentum_stored, narrative_stored = row
            name = f"{first or ''} {last or ''}".strip() or "The fighter"
            return {
                "name": name,
                "momentum_phrase": decode_phrase(momentum_stored),
                "narrative_phrase": decode_phrase(narrative_stored),
            }
        except sqlite3.Error as e:
            print(f"Warning: fighter lookup failed for id={fighter_id}: {e}",
                  flush=True)
            return None

    def _find_hottest_streak_fighter(self, conn, exclude_ids=None):
        """Find the fighter with the hottest momentum.

        Per D3: query fighter_descriptors for momentum='very_high'
        (or 'high' as fallback), EXCLUDING the given exclude_ids.
        The exclude_ids set is the Top Prospect fighter_id so the
        Hottest Streak card shows a different face when possible.

        The momentum column stores "label||phrase" — we filter on
        the LABEL using the same SUBSTR + INSTR trick the
        headline_engine uses.

        Returns:
            fighter_id (int) or None if no qualifying fighter.
        """
        exclude_ids = exclude_ids or set()
        try:
            # Try 'very_high' first, then 'high' as fallback.
            for momentum_label in ("very_high", "high"):
                rows = conn.execute(
                    """
                    SELECT fd.fighter_id
                    FROM fighter_descriptors fd
                    JOIN fighters f ON f.fighter_id = fd.fighter_id
                    WHERE f.is_active = 1 AND f.is_retired = 0
                      AND SUBSTR(fd.momentum, 1,
                                 INSTR(fd.momentum || '||', '||') - 1) = ?
                    ORDER BY fd.fighter_id ASC
                    """,
                    (momentum_label,),
                ).fetchall()
                for (fid,) in rows:
                    if fid not in exclude_ids:
                        return fid
                # If all qualifying fighters are in exclude_ids, fall
                # through to the next momentum label. If still none
                # at any label, return the first qualifying fighter
                # ignoring the exclude set (better to show someone
                # than an empty card).
                if rows:
                    return rows[0][0]
        except sqlite3.Error as e:
            print(f"Warning: hottest-streak query failed: {e}",
                  flush=True)
        return None

    def _render_watch_card(self, card_frame, title, data,
                            default_voice, empty_voice):
        """Render a single Fighter Watch card.

        Args:
            card_frame: the CTkFrame card container (built once in
                _build_fighter_watch).
            title: the card title (e.g., "TOP PROSPECT").
            data: dict from _lookup_fighter_watch_data, or None.
            default_voice: voice phrase to use if data has no
                narrative_phrase (e.g., "the wunderkind everyone's
                talking about"). Per §17.4 — the UI shows voice
                phrases, not raw labels.
            empty_voice: voice phrase for the empty state (per D6).
        """
        try:
            theme = get_theme()

            # Card title (gold H3, full-width)
            title_label = ctk.CTkLabel(
                card_frame, text=title,
                font=theme.fonts.h3, text_color=theme.colors.gold,
                anchor="w",
            )
            title_label.pack(side="top", fill="x", padx=12, pady=(10, 5))
            self._watch_cards.append(title_label)

            if data is None:
                # Empty state (D6)
                empty_label = ctk.CTkLabel(
                    card_frame, text=empty_voice,
                    font=theme.fonts.body_small,
                    text_color=theme.colors.text_tertiary,
                    anchor="w", wraplength=180, justify="left",
                )
                empty_label.pack(side="top", fill="x", padx=12, pady=(0, 12))
                self._watch_cards.append(empty_label)
                return

            # Fighter name (H3 primary)
            name_label = ctk.CTkLabel(
                card_frame, text=data["name"],
                font=theme.fonts.h3,
                text_color=theme.colors.text_primary,
                anchor="w", wraplength=180, justify="left",
            )
            name_label.pack(side="top", fill="x", padx=12, pady=(0, 3))
            self._watch_cards.append(name_label)

            # Voice phrase — prefer narrative_phrase, fall back to
            # momentum_phrase, fall back to default_voice. Per §17.4:
            # the UI shows voice phrases, never raw labels.
            voice = (data.get("narrative_phrase")
                     or data.get("momentum_phrase")
                     or default_voice)
            voice_label = ctk.CTkLabel(
                card_frame, text=voice,
                font=theme.fonts.descriptor,
                text_color=theme.colors.text_secondary,
                anchor="w", wraplength=180, justify="left",
            )
            voice_label.pack(side="top", fill="x", padx=12, pady=(0, 12))
            self._watch_cards.append(voice_label)
        except Exception as e:
            print(f"Warning: watch-card render failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Recent News (news_items — game-state news feed)
    # ------------------------------------------------------------

    def _refresh_news(self, conn):
        """Render the Recent News list.

        Per the Task 6.3 brief: "news_items is OK for display since
        it doesn't expose raw attribute values." The news feed is a
        fundamental game feature, not fighter data. We read ONLY the
        headline/topic/published_at fields — never fighter attribute
        values.
        """
        try:
            theme = get_theme()

            # Destroy old dynamic widgets (D8).
            for w in self._news_widgets:
                try:
                    w.destroy()
                except Exception:
                    pass
            self._news_widgets = []

            # Query the most recent 20 news items. ORDER BY published_at
            # DESC so the newest is at the top.
            rows = []
            try:
                rows = conn.execute(
                    "SELECT headline, topic, published_at "
                    "FROM news_items "
                    "ORDER BY published_at DESC LIMIT 20"
                ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: news_items query failed: {e}",
                      flush=True)

            if not rows:
                # Show the empty-state label (D6).
                try:
                    self.news_empty_label.configure(
                        text="The newswire is quiet.",
                        font=theme.fonts.body,
                        text_color=theme.colors.text_tertiary,
                    )
                    self.news_empty_label.pack(fill="x", padx=20, pady=30)
                except Exception:
                    pass
                return

            # Hide the empty-state label.
            try:
                self.news_empty_label.pack_forget()
            except Exception:
                pass

            # Render each news item as a row.
            for headline, topic, published_at in rows:
                row_frame = ctk.CTkFrame(
                    self.news_scroll, fg_color="transparent")
                row_frame.pack(side="top", fill="x", pady=3, padx=4)

                # Topic badge (gold bracketed label)
                topic_label = ctk.CTkLabel(
                    row_frame,
                    text=f"[{_topic_label(topic)}]",
                    font=theme.fonts.caption,
                    text_color=theme.colors.gold,
                    anchor="w",
                )
                topic_label.pack(side="left", padx=(8, 6))

                # Headline text (primary color)
                headline_text = headline or "(no headline)"
                head_label = ctk.CTkLabel(
                    row_frame, text=headline_text,
                    font=theme.fonts.body,
                    text_color=theme.colors.text_primary,
                    anchor="w",
                )
                head_label.pack(side="left", fill="x", expand=True, padx=(0, 8))

                # Date (tertiary caption, right-aligned)
                date_label = ctk.CTkLabel(
                    row_frame,
                    text=_format_date(published_at),
                    font=theme.fonts.caption,
                    text_color=theme.colors.text_tertiary,
                    anchor="e",
                )
                date_label.pack(side="right", padx=(0, 8))

                self._news_widgets.append(row_frame)
        except Exception as e:
            print(f"Warning: news refresh failed: {e}", flush=True)
