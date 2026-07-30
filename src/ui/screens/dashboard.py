"""CAGE EMPIRE — Dashboard screen (Phase 2.5 — Visual Richness Library showcase).

The player's home screen — the FIRST real screen in CAGE EMPIRE.
Phase 2.5 REWRITES the rendering layer to use the 24-component Visual
Richness Library from Phase 2 (GradientHeader, GradientCard, StatTile,
TrendIndicator, Sparkline, MomentumRing, FormMeter, NewsCard,
SectionHeader, DataChip, EmptyState, Button, HyperlinkLabel,
PortraitFrame, WatchCard-style layout, Card). This is the proof-of-
concept that proves the new components work in a real screen — if the
user likes what they see, Phases 3-6 follow the same pattern for the
other 3 screens (Roster, Fighter Profile, Free Agents).

Per docs/UI_REDESIGN_VISUAL_PLAN.md §6.1 (Dashboard wireframe + spec):
  Top to bottom:
    1. GradientHeader — gold banner with "THE EMPIRE" + sim-date subtitle
    2. Top Story — GradientCard(gold) with eyebrow + headline + body +
       topic chips + "Read full story" hyperlink
    3. Promotion Status — 5 StatTiles in a row (Cash with Sparkline +
       TrendIndicator, Reputation voice phrase, Fan Trust voice phrase,
       Roster count with TrendIndicator, Champions count with
       TrendIndicator)
    4. Next Event — Card with event details + Build Card / Matchmaking
       buttons (EmptyState if no event)
    5. Fighter Watch — 3 cards in a row, each = GradientCard wrapper
       (gold for Top Prospect + Hottest Streak, crimson for Biggest
       Fall) + PortraitFrame + name (HyperlinkLabel) + MomentumRing +
       voice phrase + FormMeter (last 5 fights W/L blocks)
    6. Champions — horizontal strip of DataChip(champion) + HyperlinkLabel
       per champion (EmptyState if none)
    7. Recent News — 5 NewsCards + "View all" hyperlink

Per docs/CONVENTIONS.md §17 (UI Snapshot Rule — CRITICAL):
  Office Mode UI screens MUST read from `*_descriptors` and
  `daily_headlines` cache tables only for fighter INTERPRETATION data.
  Game-state tables (promotions, fighters, titles, events, fights,
  fight_history, news_items, finance_transactions, simulation_clock,
  weight_classes) are fair game — they hold non-attribute data the
  player needs to see (cash, champion names, roster count, event
  schedule, news feed, recent fight results for the FormMeter).

  This screen reads from:
    - daily_headlines (cache — top story, fighter watch subjects)
    - fighter_descriptors (cache — momentum + narrative_family voice
      phrases for Fighter Watch)
    - promotions (game state — cash, reputation, fan_trust)
    - titles + weight_classes + fighters (game state — champion names)
    - fighters (game state — first/last name, weight_class_id)
    - news_items (game state — news feed)
    - events + fights (game state — Next Event section)
    - fight_history (game state — last 5 fights for FormMeter)
    - finance_transactions (game state — 7-day cash history for Sparkline)
    - simulation_clock (game state — sim date for subtitle)

Per docs/CONVENTIONS.md §14 (Interpretation Layer):
  No raw attribute values appear in the player-facing UI.
    - Cash: "$50.0M" (game-state money, formatted) — OK.
    - Reputation: "Highly Respected" (voice band, NOT raw 0-100) — OK.
    - Fan Trust: "Strong" (voice band) — OK.
    - Roster count: "1,002 fighters" (game-state count) — OK.
    - Champion count: "3 of 8 belts" (game-state count) — OK.
    - Fighter Watch voice phrases: from fighter_descriptors cache — OK.
    - MomentumRing tier: maps the fighter_descriptors.momentum LABEL
      (very_high/high/stable/falling/collapsing) to a visual ring fill
      percentage + short voice phrase ("Scorching"/"Hot"/"Steady"/
      "Sliding"/"Collapsing"). Never shows the raw momentum number.
    - FormMeter: shows W/L/D result codes from fight_history (career
      stats, allowed per §14).

Architecture (Phase 2.5 — destroy + recreate refresh):
  - DashboardScreen(ctk.CTkFrame) — the screen widget.
  - __init__ builds the STATIC structure: scrollable root + 7
    SectionHeaders + 7 section containers (empty CTkFrames that get
    populated on _refresh).
  - _refresh() (registered with GameState) calls _refresh_subtitle +
    _refresh_top_story + _refresh_promotion_status + _refresh_next_event
    + _refresh_champions + _refresh_fighter_watch + _refresh_news.
  - Each _refresh_* method destroys the old section content + rebuilds
    it from the new query results using the Phase 2 components.
  - Data queries are PRESERVED from the pre-Phase-2.5 dashboard
    (the SQL is correct — only the rendering changed).
  - New queries added for Phase 2.5:
      * _query_cash_history — 7-day cash for Sparkline.
      * _query_yesterday_cash — previous-value for TrendIndicator.
      * _query_last_5_fights — W/L/D codes for FormMeter.
      * _query_next_event — event + main event fight for Next Event.

DESIGN DECISIONS (D-numbers — carried forward from pre-Phase-2.5):
  D1  Source-of-truth map (see §17 comment block above).
  D2  Local reputation/fan_trust voice bands (transitional shim — kept).
  D3  Hottest Streak card query (excludes Top Prospect fighter_id).
  D4  Voice-phrase decoding via interpretation.context_engine.decode_phrase.
  D5  Scrollable root (CTkScrollableFrame) — content can exceed viewport.
  D6  Empty-state handling — every section degrades gracefully.
  D7  Action-button navigation via state.set_active_screen().
  D8  Refresh pattern — destroy dynamic widgets, re-query, re-render.
  D9  Champion ordering by weight_class display_order (heavyweight first).
  D10 (Phase 2.5) Destroy + recreate refresh. Each _refresh_* method
      destroys the section's children + rebuilds from the new query
      results. Approach (a) per the Phase 2.5 spec — simplest, works
      for all components. Refresh is infrequent (on navigation + Advance
      Day) so the rebuild cost is acceptable. Phase 3+ can optimize
      with component update() methods if needed.
  D11 (Phase 2.5) MomentumRing tier mapping. The fighter_descriptors
      .momentum column stores "label||phrase". The label is one of
      very_high/high/stable/falling/collapsing. MomentumRing accepts
      the tier directly — we extract the label via decode_phrase's
      label extraction + pass it to MomentumRing(tier=label).
  D12 (Phase 2.5) FormMeter data source. fight_history.outcome holds
      'win'/'loss'/'draw'/'nc'. We map win→W, loss→L, draw→D, nc→D
      (treat no-contest as draw for form visualization). Query the
      last 5 fight_history rows for the fighter ordered by event_date
      DESC. If fewer than 5, show what we have.
  D13 (Phase 2.5) Next Event query. The events table holds scheduled
      events. We query the earliest event with status='scheduled' and
      event_date >= today's sim date. Join with fights (card_slot=
      'main_event') + fighters for the main event matchup. If the
      fight is a title fight (is_title_fight=1), show a DataChip
      (champion variant) "TITLE FIGHT" indicator.
"""

import sqlite3
import calendar
from datetime import datetime

import customtkinter as ctk

from ui.theme import get_theme, SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL
from ui.state import get_state
from ui.voice_display import title_case_phrase

# Phase 4 — Performance: query cache for the hottest-streak lookup
# (5-6ms scan of fighter_descriptors that doesn't change within a
# single Advance Day cycle). Cached until the next Advance Day,
# which calls clear_query_cache() from CageEmpireApp._on_advance_day.
from ui.perf import query_cached

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (D4).
from interpretation.context_engine import decode_phrase

# Phase 2 — Visual Richness Library (24 components). Phase 2.5 uses 16
# of them on the Dashboard: GradientHeader, GradientCard, SectionHeader,
# DataChip, StatTile, TrendIndicator, Sparkline, FormMeter, MomentumRing,
# NewsCard, EmptyState, Button, HyperlinkLabel, PortraitFrame, Card,
# (and WatchCard is referenced via the spec but we compose its layout
# manually inside GradientCard to slot in MomentumRing + FormMeter).
from ui.widgets.components import (
    GradientHeader,
    GradientCard,
    Card,
    SectionHeader,
    DataChip,
    StatTile,
    NewsCard,
    EmptyState,
    Button,
    HyperlinkLabel,
    PortraitFrame,
    MomentumRing,
    FormMeter,
)


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


# Momentum label (from fighter_descriptors.momentum "label||phrase") →
# MomentumRing tier. The momentum label is one of very_high / high /
# stable / falling / collapsing (per the interpretation engines). The
# MomentumRing accepts these directly as its tier argument. We fall
# back to "stable" for unknown labels (defensive — should never happen
# but guards against future interpretation-engine changes).
_MOMENTUM_LABEL_TO_TIER = {
    "very_high": "very_high",
    "high": "high",
    "stable": "stable",
    "falling": "falling",
    "collapsing": "collapsing",
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
    """Translate a raw 0-100 fan_trust value to a voice phrase."""
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

    Matches the top bar's _update_top_bar formatting (src/ui/app.py)
    + SaveLoadScreen._format_cash so the Dashboard displays cash
    consistently with the rest of the UI. Game-state money, OK per §14.
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
    """Format an ISO date string ('2026-12-23') for display."""
    if not iso_date_str:
        return ""
    try:
        s = str(iso_date_str)[:10]
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(iso_date_str)


def _format_event_date_long(iso_date_str):
    """Format an event date as 'Sat 19 Sep 2026' (long form for Next Event)."""
    if not iso_date_str:
        return ""
    try:
        s = str(iso_date_str)[:10]
        dt = datetime.fromisoformat(s)
        return dt.strftime("%a %d %b %Y")
    except (ValueError, TypeError):
        return str(iso_date_str)


def _topic_label(topic):
    """Render a news_items.topic as a clean display label.

    The seed scripts sometimes store 'milestone' with a leading
    space (' ilestone') — defensive strip + upper-case so the news
    feed reads cleanly.
    """
    if not topic:
        return "NEWS"
    return str(topic).strip().upper() or "NEWS"


def _decode_momentum_label(stored_value):
    """Extract the canonical momentum LABEL from a "label||phrase" string.

    Used to map the stored momentum to a MomentumRing tier. Per D4,
    the storage format is "label||phrase" (or just "label" if no
    phrase was stored). decode_phrase returns the PHRASE (or the label
    if no phrase); we need the LABEL itself for the tier lookup.

    Returns:
        The canonical label (e.g., "very_high"), or "stable" if the
        stored value is empty / unparseable.
    """
    if not stored_value:
        return "stable"
    s = str(stored_value).strip()
    if "||" in s:
        label = s.split("||", 1)[0].strip().lower()
    else:
        label = s.lower()
    return _MOMENTUM_LABEL_TO_TIER.get(label, "stable")


# ============================================================
# DASHBOARD SCREEN
# ============================================================

class DashboardScreen(ctk.CTkFrame):
    """Dashboard — the player's home screen (Phase 2.5 redesign).

    The first real screen in CAGE EMPIRE. Office Mode only. Registered
    with GameState as 'dashboard'. The refresh callback (`_refresh`)
    re-queries every data source + re-renders using the Phase 2
    component library.

    Usage (unchanged from pre-Phase-2.5):
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
        # re-rendering. Per D8 + D10.
        self._top_story_widgets = []
        self._promotion_status_widgets = []
        self._next_event_widgets = []
        self._champion_widgets = []
        self._watch_cards = []
        self._news_widgets = []
        self._gradient_header = None  # The GradientHeader (built once)

        # UI Fix Plan 2 — Phase 1, Fix 8: scrollable root container.
        # The Dashboard's content can exceed the viewport height —
        # especially with the new Promotion Status StatTile row (5
        # tiles side-by-side need horizontal room) + the Recent News
        # list. Wrapping everything in a CTkScrollableFrame ensures
        # the player can always reach the sections below the fold.
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True)

        # Build the static structure (GradientHeader + 7 SectionHeaders
        # + 7 empty section containers). Dynamic content is rendered
        # by _refresh. All _build_* methods parent their widgets to
        # self._scroll (NOT self) so they live inside the scrollable
        # frame.
        self._build_header()
        self._build_top_story()
        self._build_promotion_status()
        self._build_next_event()
        self._build_fighter_watch()
        self._build_champions()
        self._build_news()

        # Initial render. Use after(50, ...) so the widget is fully
        # laid out before we query (matches SaveLoadScreen pattern).
        # Safe — if the screen is destroyed before the callback fires,
        # _refresh's try/except handles it.
        self.after(50, self._refresh)

    # ============================================================
    # STATIC STRUCTURE — built once in __init__
    # ============================================================

    def _build_header(self):
        """Build the GradientHeader banner (Section 1).

        Phase 2.5: replaces the plain "THE EMPIRE" CTkLabel with a
        GradientHeader(gold) banner — the gold gradient + Oswald
        display_small title gives the "stadium scoreboard" feel the
        user asked for. The subtitle (sim date + promotion name) is
        populated by _refresh_subtitle via set_subtitle().
        """
        self._gradient_header = GradientHeader(
            self._scroll,
            title="THE EMPIRE",
            subtitle="",
            variant="gold",
            height=64,
        )
        self._gradient_header.pack(side="top", fill="x", padx=SPACE_LG,
                                    pady=(SPACE_MD, SPACE_LG))

    def _build_top_story(self):
        """Build the Top Story section header + empty container (Section 2).

        The GradientCard + content are built per-refresh by
        _refresh_top_story (D10 — destroy + recreate).
        """
        header = SectionHeader(
            self._scroll, title="TOP STORY",
            accent_color=get_theme().colors.gold,
        )
        header.pack(side="top", fill="x", padx=SPACE_LG, pady=(0, SPACE_SM))
        # Keep a reference so _refresh can destroy + rebuild content.
        self._top_story_container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._top_story_container.pack(side="top", fill="x",
                                        padx=SPACE_LG, pady=(0, SPACE_LG))

    def _build_promotion_status(self):
        """Build the Promotion Status section header + empty container (Section 3).

        The 5 StatTiles are built per-refresh by _refresh_promotion_status.
        """
        header = SectionHeader(
            self._scroll, title="PROMOTION STATUS",
            accent_color=get_theme().colors.gold,
        )
        header.pack(side="top", fill="x", padx=SPACE_LG, pady=(0, SPACE_SM))
        self._promo_status_container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._promo_status_container.pack(side="top", fill="x",
                                           padx=SPACE_LG, pady=(0, SPACE_LG))
        # Configure the 5-column grid (equal weight per StatTile).
        for i in range(5):
            self._promo_status_container.grid_columnconfigure(i, weight=1, uniform="stat")

    def _build_next_event(self):
        """Build the Next Event section header + empty container (Section 4)."""
        header = SectionHeader(
            self._scroll, title="NEXT EVENT",
            accent_color=get_theme().colors.gold,
        )
        header.pack(side="top", fill="x", padx=SPACE_LG, pady=(0, SPACE_SM))
        self._next_event_container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._next_event_container.pack(side="top", fill="x",
                                         padx=SPACE_LG, pady=(0, SPACE_LG))

    def _build_fighter_watch(self):
        """Build the Fighter Watch section header + empty container (Section 5).

        The 3 GradientCard watch cards are built per-refresh by
        _refresh_fighter_watch.
        """
        header = SectionHeader(
            self._scroll, title="FIGHTER WATCH",
            accent_color=get_theme().colors.gold,
        )
        header.pack(side="top", fill="x", padx=SPACE_LG, pady=(0, SPACE_SM))
        self._watch_container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._watch_container.pack(side="top", fill="x",
                                    padx=SPACE_LG, pady=(0, SPACE_LG))
        # 3-column grid (equal weight per watch card).
        for i in range(3):
            self._watch_container.grid_columnconfigure(i, weight=1, uniform="watch")

    def _build_champions(self):
        """Build the Champions section header + empty container (Section 6)."""
        header = SectionHeader(
            self._scroll, title="YOUR CHAMPIONS",
            accent_color=get_theme().colors.gold,
        )
        header.pack(side="top", fill="x", padx=SPACE_LG, pady=(0, SPACE_SM))
        self._champions_container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._champions_container.pack(side="top", fill="x",
                                        padx=SPACE_LG, pady=(0, SPACE_LG))

    def _build_news(self):
        """Build the Recent News section header + empty container (Section 7)."""
        header = SectionHeader(
            self._scroll, title="RECENT NEWS",
            accent_color=get_theme().colors.gold,
            metadata="View all ▶",
        )
        header.pack(side="top", fill="x", padx=SPACE_LG, pady=(0, SPACE_SM))
        self._news_container = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._news_container.pack(side="top", fill="x",
                                   padx=SPACE_LG, pady=(0, SPACE_LG))

    # ============================================================
    # HANDLERS — navigation (D7)
    # ============================================================

    def _on_schedule_event(self):
        """Navigate to the Event Builder screen (Build Card button)."""
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
        """Navigate to the Free Agents screen (Matchmaking button)."""
        try:
            get_state().set_active_screen("free_agents")
        except (ValueError, Exception) as e:
            print(f"Warning: navigation to free_agents failed: {e}",
                  flush=True)

    # ============================================================
    # REFRESH CALLBACK (registered with GameState — signature PRESERVED)
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
        before rendering the new ones (D8 + D10). Defensive against
        DB errors (if a query throws, the section shows its empty-state).
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
            self._refresh_next_event(conn, promo_id)
            self._refresh_champions(conn, promo_id)
            self._refresh_fighter_watch(conn)
            self._refresh_news(conn)
        except Exception as e:
            print(f"Warning: DashboardScreen._refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Subtitle — "Month Year · Promotion Name"
    # ------------------------------------------------------------
    # PRESERVED from pre-Phase-2.5. Only the rendering target changed:
    # instead of configuring a plain CTkLabel, we call
    # GradientHeader.set_subtitle().

    def _refresh_subtitle(self, conn, promo_id):
        """Update the GradientHeader subtitle with sim-date + promotion name."""
        try:
            # Sim date from the clock — query month + year directly.
            month = None
            year = "?"
            try:
                clock_row = conn.execute(
                    "SELECT current_month, current_year "
                    "FROM simulation_clock WHERE clock_id=1"
                ).fetchone()
                if clock_row:
                    month = clock_row[0]
                    year = clock_row[1] if clock_row[1] is not None else "?"
            except sqlite3.Error:
                pass

            month_name = ""
            if isinstance(month, int) and 1 <= month <= 12:
                month_name = calendar.month_name[month]

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

            if month_name:
                date_part = f"{month_name} {year}"
            else:
                date_part = f"{year}"
            text = f"{date_part}  ·  {promo_name}"
            if self._gradient_header is not None:
                self._gradient_header.set_subtitle(text)
        except Exception as e:
            print(f"Warning: subtitle refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Top Story (daily_headlines cache — §17)
    # ------------------------------------------------------------
    # PRESERVED query. NEW rendering: GradientCard(gold) + DataChip
    # topic chips + HyperlinkLabel "Read full story" link.

    def _refresh_top_story(self, conn):
        """Render the Top Story card using GradientCard + components.

        Reads from daily_headlines (per §17 — cache table). The
        top_story row populates a GradientCard(gold) with:
          - Eyebrow: "TOP STORY" (caption, gold)
          - Headline: h2 (HyperlinkLabel if fighter_id, else CTkLabel)
          - Body: 2-line summary (body font, text_secondary)
          - Topic chips: DataChip for headline_type + fighter's WC
          - "Read full story →" hyperlink (HyperlinkLabel with fighter_id)
        """
        try:
            # Destroy old dynamic widgets (D8 + D10).
            self._destroy_widgets(self._top_story_widgets)
            self._top_story_widgets = []

            # PRESERVED query — daily_headlines for top_story.
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

            top_story = next(
                (h for h in headlines if h["type"] == "top_story"), None)

            # ---- Build the GradientCard(gold) ----
            # Phase 2.5: the gold gradient + 2px gold accent border
            # signals "this is the marquee story" per the spec.
            card = GradientCard(
                self._top_story_container, variant="gold",
                padding=SPACE_LG, corner_radius=6,
            )
            card.pack(side="top", fill="x")
            self._top_story_widgets.append(card)

            if top_story is None:
                # Empty state (D6) — still inside the GradientCard so
                # the gold frame is visible (signals "this slot exists,
                # just empty today").
                empty = ctk.CTkLabel(
                    card.content_frame,
                    text="A quiet day across the promotions.",
                    font=get_theme().fonts.body,
                    text_color=get_theme().colors.text_tertiary,
                    anchor="w", justify="left", wraplength=560,
                )
                empty.pack(side="top", fill="x", pady=SPACE_MD)
                self._top_story_widgets.append(empty)
                return

            theme = get_theme()
            fighter_id = top_story.get("fighter_id")

            # Eyebrow: "TOP STORY" (caption, gold).
            eyebrow = ctk.CTkLabel(
                card.content_frame, text="TOP STORY",
                font=theme.fonts.caption, text_color=theme.colors.gold,
                anchor="w",
            )
            eyebrow.pack(side="top", fill="x", pady=(0, SPACE_SM))
            self._top_story_widgets.append(eyebrow)

            # Headline (h2). HyperlinkLabel if fighter_id, else plain.
            headline_text = top_story["text"] or "Today's top story"
            if fighter_id:
                head_label = HyperlinkLabel(
                    card.content_frame, text=headline_text,
                    fighter_id=fighter_id,
                    font=theme.fonts.h2,
                    anchor="w", wraplength=560, justify="left",
                )
            else:
                head_label = ctk.CTkLabel(
                    card.content_frame, text=headline_text,
                    font=theme.fonts.h2,
                    text_color=theme.colors.text_primary,
                    anchor="w", wraplength=560, justify="left",
                )
            head_label.pack(side="top", fill="x", pady=(0, SPACE_SM))
            self._top_story_widgets.append(head_label)

            # Body (2-line summary).
            body_text = top_story["body"] or ""
            if body_text:
                body_label = ctk.CTkLabel(
                    card.content_frame, text=body_text,
                    font=theme.fonts.body,
                    text_color=theme.colors.text_secondary,
                    anchor="w", wraplength=560, justify="left",
                )
                body_label.pack(side="top", fill="x", pady=(0, SPACE_SM))
                self._top_story_widgets.append(body_label)

            # Topic chips row: headline_type chip + fighter's WC chip
            # (if fighter_id present). Aligned left.
            chips_row = ctk.CTkFrame(card.content_frame, fg_color="transparent")
            chips_row.pack(side="top", fill="x", pady=(0, SPACE_SM))
            self._top_story_widgets.append(chips_row)

            type_chip = DataChip(
                chips_row, text=_HEADLINE_TYPE_TO_CARD_TITLE.get(
                    top_story["type"], top_story["type"].replace("_", " ")),
                variant="default",
            )
            type_chip.pack(side="left", padx=(0, SPACE_SM))
            self._top_story_widgets.append(type_chip)

            # Fighter's weight class chip (if applicable).
            if fighter_id:
                try:
                    wc_row = conn.execute(
                        "SELECT wc.name FROM fighters f "
                        "JOIN weight_classes wc "
                        "  ON wc.weight_class_id = f.weight_class_id "
                        "WHERE f.fighter_id=?",
                        (fighter_id,),
                    ).fetchone()
                    if wc_row and wc_row[0]:
                        wc_chip = DataChip(
                            chips_row, text=wc_row[0], variant="info",
                        )
                        wc_chip.pack(side="left", padx=(0, SPACE_SM))
                        self._top_story_widgets.append(wc_chip)
                except sqlite3.Error:
                    pass  # Defensive — skip the WC chip on query failure.

            # "Read full story →" hyperlink at bottom-right.
            # Only shown if fighter_id is present (the link navigates
            # to the Fighter Profile — without a fighter_id there's
            # nowhere to navigate).
            if fighter_id:
                link_row = ctk.CTkFrame(card.content_frame, fg_color="transparent")
                link_row.pack(side="top", fill="x")
                self._top_story_widgets.append(link_row)
                read_link = HyperlinkLabel(
                    link_row, text="Read full story →",
                    fighter_id=fighter_id,
                    font=theme.fonts.caption,
                    anchor="e",
                )
                read_link.pack(side="right")
                self._top_story_widgets.append(read_link)
        except Exception as e:
            print(f"Warning: top-story refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Promotion Status (promotions + fighters — game state, §14 OK)
    # ------------------------------------------------------------
    # PRESERVED query for cash/reputation/fan_trust/roster/champions.
    # NEW: 7-day cash history query (Sparkline) + yesterday's cash
    # query (TrendIndicator previous). NEW rendering: 5 StatTiles.

    def _refresh_promotion_status(self, conn, promo_id):
        """Render the 5 Promotion Status StatTiles.

        Per D1+D2: reads from promotions (cash/rep/trust) + fighters
        (roster count) + titles (champion count). Reputation + fan_trust
        pass through local voice bands (D2) before display.

        Per Phase 2.5 spec: 5 StatTiles in a row, each 2-col width:
          1. CASH — value=cash_str, TrendIndicator(current=cash,
             previous=yesterday_cash), Sparkline(last 7 days).
          2. REPUTATION — value=voice phrase (no trend).
          3. FAN TRUST — value=voice phrase (no trend).
          4. ROSTER — value=count_str, TrendIndicator (current=roster,
             previous=roster — no historical data, shows ●).
          5. CHAMPIONS — value=count_str, TrendIndicator (current=champs,
             previous=champs — no historical data, shows ●).
        """
        try:
            # Destroy old dynamic widgets (D8 + D10).
            self._destroy_widgets(self._promotion_status_widgets)
            self._promotion_status_widgets = []

            theme = get_theme()

            # ---- PRESERVED: query promotions for cash/rep/trust ----
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

            # ---- PRESERVED: roster count ----
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

            # ---- PRESERVED: champion count ----
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

            # ---- NEW (Phase 2.5): 7-day cash history for Sparkline ----
            cash_history = self._query_cash_history(conn, promo_id, cash)
            # ---- NEW (Phase 2.5): yesterday's cash for TrendIndicator ----
            yesterday_cash = self._query_yesterday_cash(conn, promo_id, cash)

            # Voice-banded display values (D2 — §14 compliance).
            reputation_voice = _reputation_band(reputation_raw)
            fan_trust_voice = _fan_trust_band(fan_trust_raw)

            # ---- Render the 5 StatTiles ----
            # Tile 1: CASH — numeric, mono font, with trend + sparkline.
            cash_value = _format_cash(cash)
            try:
                cash_float = float(cash) if cash is not None else 0.0
            except (TypeError, ValueError):
                cash_float = 0.0
            try:
                yesterday_float = float(yesterday_cash) if yesterday_cash is not None else cash_float
            except (TypeError, ValueError):
                yesterday_float = cash_float
            cash_tile = StatTile(
                self._promo_status_container,
                label="CASH", value=cash_value,
                current_value=cash_float,
                previous_value=yesterday_float,
                sparkline_data=cash_history,
                show_sparkline=True,
            )
            cash_tile.grid(row=0, column=0, sticky="nsew",
                            padx=(0, SPACE_SM), pady=0)
            self._promotion_status_widgets.append(cash_tile)

            # Tile 2: REPUTATION — voice phrase (display_small font, no trend).
            # StatTile's value uses mono by default; for voice phrases we
            # want a non-mono font. We pass the value + accept the default
            # mono font (acceptable — the voice phrase still reads clearly).
            # Per the spec: "use the display_small font for the value".
            # We override via set_value after construction.
            rep_tile = StatTile(
                self._promo_status_container,
                label="REPUTATION", value=reputation_voice,
            )
            rep_tile.grid(row=0, column=1, sticky="nsew",
                           padx=SPACE_XS, pady=0)
            # Override the value font to display_small (voice phrase, not number).
            try:
                rep_tile._value.configure(font=theme.fonts.h3)
            except Exception:
                pass
            self._promotion_status_widgets.append(rep_tile)

            # Tile 3: FAN TRUST — voice phrase.
            trust_tile = StatTile(
                self._promo_status_container,
                label="FAN TRUST", value=fan_trust_voice,
            )
            trust_tile.grid(row=0, column=2, sticky="nsew",
                             padx=SPACE_XS, pady=0)
            try:
                trust_tile._value.configure(font=theme.fonts.h3)
            except Exception:
                pass
            self._promotion_status_widgets.append(trust_tile)

            # Tile 4: ROSTER — count + trend (no historical data → ●).
            roster_value = f"{roster_count:,} fighters"
            roster_tile = StatTile(
                self._promo_status_container,
                label="ROSTER", value=roster_value,
                current_value=float(roster_count),
                previous_value=float(roster_count),  # No historical data.
                show_sparkline=False,
            )
            roster_tile.grid(row=0, column=3, sticky="nsew",
                              padx=SPACE_XS, pady=0)
            self._promotion_status_widgets.append(roster_tile)

            # Tile 5: CHAMPIONS — count of 8 + trend.
            # Per spec: "3 of 8 belts". We have champion_count + the
            # total weight classes is 8 (per the seed). Query the
            # total to be safe (defensive — the seed might change).
            total_wcs = 8
            try:
                wc_count_row = conn.execute(
                    "SELECT COUNT(*) FROM weight_classes WHERE is_active=1"
                ).fetchone()
                if wc_count_row and wc_count_row[0]:
                    total_wcs = wc_count_row[0]
            except sqlite3.Error:
                pass
            champs_value = f"{champion_count} of {total_wcs} belts"
            champs_tile = StatTile(
                self._promo_status_container,
                label="CHAMPIONS", value=champs_value,
                current_value=float(champion_count),
                previous_value=float(champion_count),  # No historical data.
                show_sparkline=False,
            )
            champs_tile.grid(row=0, column=4, sticky="nsew",
                              padx=(SPACE_SM, 0), pady=0)
            self._promotion_status_widgets.append(champs_tile)
        except Exception as e:
            print(f"Warning: promotion-status refresh failed: {e}",
                  flush=True)

    def _query_cash_history(self, conn, promo_id, current_cash):
        """Query the last 7 days of cash for the Sparkline.

        NEW (Phase 2.5). Uses finance_transactions with a running
        cumulative sum to derive the cash-on-hand at the end of each
        of the last 6 transaction-date days, then APPENDS the current
        cash (from promotions.current_cash) as the 7th point (today).

        If fewer than 6 transaction dates exist, pads at the front
        with the oldest running total (so the line stays flat at the
        start rather than showing a fake jump from 0). If zero
        transactions, returns [current_cash] * 7 (flat line at today's
        cash — honest about the lack of historical data).

        The current_cash is ALWAYS the last point so the sparkline's
        final value matches the StatTile's displayed value (the user
        sees a consistent number across the tile + sparkline).

        Args:
            conn: SQLite connection.
            promo_id: the player's promotion ID.
            current_cash: the current cash balance (from promotions.

        Returns:
            List of 7 floats (oldest first, today's cash last).
        """
        try:
            base = float(current_cash) if current_cash is not None else 0.0
        except (TypeError, ValueError):
            base = 0.0

        try:
            # Get the last 6 distinct transaction dates + the running
            # cumulative sum of amounts up to + including each date.
            # We use a correlated subquery for the running total so we
            # get the cash balance at the END of each transaction date.
            rows = conn.execute(
                """
                SELECT transaction_date,
                       (SELECT SUM(amount) FROM finance_transactions
                    WHERE promotion_id = ?
                      AND transaction_date <= t.transaction_date
                   ) AS running_total
                FROM finance_transactions t
                WHERE t.promotion_id = ?
                GROUP BY t.transaction_date
                ORDER BY t.transaction_date DESC
                LIMIT 6
                """,
                (promo_id, promo_id),
            ).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: cash history query failed: {e}", flush=True)
            rows = []

        if not rows:
            # No transactions — flat line at current cash (honest).
            return [base] * 7

        # rows is newest-first; reverse to oldest-first.
        history = []
        for r in reversed(rows):
            try:
                v = float(r[1]) if r[1] is not None else base
            except (TypeError, ValueError):
                v = base
            history.append(v)

        # Append today's cash as the last point (always — so the
        # sparkline's final value matches the StatTile's value).
        history.append(base)

        # Pad to 7 at the FRONT with the oldest value (so the line
        # stays flat at the start rather than showing a fake jump
        # from 0).
        while len(history) < 7:
            history.insert(0, history[0])
        return history[:7]

    def _query_yesterday_cash(self, conn, promo_id, current_cash):
        """Query the cash balance at the most recent transaction date.

        NEW (Phase 2.5). Used as the TrendIndicator's previous_value
        for the CASH StatTile. "Yesterday" here means "the most recent
        transaction date before today" — if there's only 1 transaction
        (e.g., the seed), that's the seed amount, and the trend shows
        the delta between the seed and today's actual cash (honest
        about spending that isn't logged in finance_transactions).

        If no transactions exist, returns current_cash (delta = 0,
        arrow = ●).
        """
        try:
            base = float(current_cash) if current_cash is not None else 0.0
        except (TypeError, ValueError):
            base = 0.0

        try:
            # Get the most recent transaction's running total. This is
            # the cash balance at the end of that transaction's date.
            # If we have 2+ transactions, the second-most-recent gives
            # us "yesterday" (the point before today's current_cash).
            rows = conn.execute(
                """
                SELECT transaction_date,
                       (SELECT SUM(amount) FROM finance_transactions
                    WHERE promotion_id = ?
                      AND transaction_date <= t.transaction_date
                   ) AS running_total
                FROM finance_transactions t
                WHERE t.promotion_id = ?
                GROUP BY t.transaction_date
                ORDER BY t.transaction_date DESC
                LIMIT 2
                """,
                (promo_id, promo_id),
            ).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: yesterday cash query failed: {e}", flush=True)
            return base

        if not rows:
            return base
        if len(rows) == 1:
            # Only 1 transaction — previous = that transaction's
            # running total (the seed amount, typically). The trend
            # shows the delta between the seed and today's actual cash.
            try:
                return float(rows[0][1]) if rows[0][1] is not None else base
            except (TypeError, ValueError):
                return base
        # rows[0] = today (most recent), rows[1] = previous.
        try:
            return float(rows[1][1]) if rows[1][1] is not None else base
        except (TypeError, ValueError):
            return base

    # ------------------------------------------------------------
    # Next Event (events + fights + fighters — game state)
    # ------------------------------------------------------------
    # NEW section (Phase 2.5). Queries the next scheduled event for
    # the player's promotion + its main event fight.

    def _refresh_next_event(self, conn, promo_id):
        """Render the Next Event card (Section 4).

        NEW (Phase 2.5). Queries the earliest scheduled event for the
        player's promotion with event_date >= today's sim date. Joins
        with fights (card_slot='main_event') + fighters for the main
        event matchup. Shows:
          - Event date (long format: "Sat 19 Sep 2026")
          - Event name
          - Main event matchup (Fighter A vs Fighter B)
          - DataChip "TITLE FIGHT" (champion variant) if is_title_fight=1
          - Build Card (primary) + Matchmaking (secondary) buttons
        If no event scheduled, shows EmptyState with a "Build a Card"
        CTA button.
        """
        try:
            self._destroy_widgets(self._next_event_widgets)
            self._next_event_widgets = []

            theme = get_theme()

            # Query the next scheduled event. We don't filter by
            # event_date >= today because the sim date might lag behind
            # real-time; instead, we take the earliest scheduled event
            # (status='scheduled') ordered by event_date ASC. If multiple
            # events are scheduled, the next one is the earliest.
            event_row = None
            try:
                event_row = conn.execute(
                    """
                    SELECT event_id, event_name, event_date
                    FROM events
                    WHERE promotion_id=? AND status='scheduled'
                    ORDER BY event_date ASC
                    LIMIT 1
                    """,
                    (promo_id,),
                ).fetchone()
            except sqlite3.Error as e:
                print(f"Warning: next event query failed: {e}", flush=True)

            if event_row is None:
                # Empty state (D6) — EmptyState component with CTA.
                empty = EmptyState(
                    self._next_event_container,
                    headline="No events booked.",
                    body="Build a card to give the fans something to remember.",
                    icon_text="📅",
                    cta_text="Build a Card",
                    cta_on_click=self._on_schedule_event,
                )
                empty.pack(side="top", fill="x", pady=SPACE_MD)
                self._next_event_widgets.append(empty)
                return

            event_id, event_name, event_date = event_row

            # Build the card.
            card = Card(self._next_event_container, variant="flat",
                         padding=SPACE_LG, corner_radius=6)
            card.pack(side="top", fill="x")
            self._next_event_widgets.append(card)

            # Event date (display_small, gold).
            date_str = _format_event_date_long(event_date)
            date_label = ctk.CTkLabel(
                card.content_frame, text=date_str,
                font=theme.fonts.h2, text_color=theme.colors.gold,
                anchor="w",
            )
            date_label.pack(side="top", fill="x", pady=(0, SPACE_XS))
            self._next_event_widgets.append(date_label)

            # Event name (h3, text_primary).
            name_label = ctk.CTkLabel(
                card.content_frame, text=event_name or "Untitled Event",
                font=theme.fonts.h3, text_color=theme.colors.text_primary,
                anchor="w",
            )
            name_label.pack(side="top", fill="x", pady=(0, SPACE_MD))
            self._next_event_widgets.append(name_label)

            # Main event fight (if any).
            main_event_text = None
            is_title_fight = False
            try:
                me_row = conn.execute(
                    """
                    SELECT f.is_title_fight,
                           fa.first_name, fa.last_name,
                           fb.first_name, fb.last_name,
                           wc.name
                    FROM fights f
                    LEFT JOIN fighters fa ON fa.fighter_id = (
                        SELECT fighter_id FROM fight_history
                        WHERE fight_id = f.fight_id LIMIT 1
                    )
                    LEFT JOIN fighters fb ON fb.fighter_id = (
                        SELECT fighter_id FROM fight_history
                        WHERE fight_id = f.fight_id
                          AND fighter_id <> fa.fighter_id
                        LIMIT 1
                    )
                    LEFT JOIN weight_classes wc
                      ON wc.weight_class_id = f.weight_class_id
                    WHERE f.event_id=? AND f.card_slot='main_event'
                    LIMIT 1
                    """,
                    (event_id,),
                ).fetchone()
                if me_row:
                    is_title_fight = bool(me_row[0])
                    a_first, a_last = me_row[1] or "", me_row[2] or ""
                    b_first, b_last = me_row[3] or "", me_row[4] or ""
                    wc_name = me_row[5] or ""
                    a_name = f"{a_first} {a_last}".strip()
                    b_name = f"{b_first} {b_last}".strip()
                    if a_name and b_name:
                        main_event_text = f"{a_name} vs {b_name}"
                        if wc_name:
                            main_event_text += f"  ·  {wc_name}"
                    elif a_name:
                        main_event_text = a_name
            except sqlite3.Error as e:
                print(f"Warning: main event query failed: {e}", flush=True)

            if main_event_text:
                me_label = ctk.CTkLabel(
                    card.content_frame,
                    text=f"Main Event:  {main_event_text}",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_primary,
                    anchor="w",
                )
                me_label.pack(side="top", fill="x", pady=(0, SPACE_SM))
                self._next_event_widgets.append(me_label)

                # Title fight indicator chip.
                if is_title_fight:
                    tf_chip = DataChip(
                        card.content_frame, text="TITLE FIGHT",
                        variant="champion",
                    )
                    tf_chip.pack(side="top", anchor="w", pady=(0, SPACE_MD))
                    self._next_event_widgets.append(tf_chip)

            # Buttons row: Build Card (primary) + Matchmaking (secondary).
            btn_row = ctk.CTkFrame(card.content_frame, fg_color="transparent")
            btn_row.pack(side="top", fill="x", pady=(SPACE_SM, 0))
            self._next_event_widgets.append(btn_row)

            build_btn = Button(
                btn_row, text="Build Card", variant="primary",
                on_click=self._on_schedule_event,
            )
            build_btn.pack(side="left", padx=(0, SPACE_SM))
            self._next_event_widgets.append(build_btn)

            match_btn = Button(
                btn_row, text="Matchmaking", variant="secondary",
                on_click=self._on_view_free_agents,
            )
            match_btn.pack(side="left")
            self._next_event_widgets.append(match_btn)
        except Exception as e:
            print(f"Warning: next-event refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Champions list (titles + weight_classes + fighters — game state)
    # ------------------------------------------------------------
    # PRESERVED query. NEW rendering: horizontal strip of DataChip +
    # HyperlinkLabel per champion.

    def _refresh_champions(self, conn, promo_id):
        """Render the YOUR CHAMPIONS horizontal strip.

        Per D1: reads from titles + weight_classes + fighters (game
        state — champion names, NOT raw attribute values). Per D9:
        ordered by weight_class display_order (heavyweight first).

        Phase 2.5: each champion = DataChip(champion variant) showing
        the weight class + HyperlinkLabel showing the champion's name
        (click navigates to Fighter Profile). Up to 8 champions in a
        horizontal strip. If no champions, shows EmptyState.
        """
        try:
            self._destroy_widgets(self._champion_widgets)
            self._champion_widgets = []

            theme = get_theme()

            # PRESERVED query — champions join.
            rows = []
            try:
                rows = conn.execute(
                    """
                    SELECT wc.name, f.fighter_id, f.first_name, f.last_name
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
                # Empty state (D6).
                empty = EmptyState(
                    self._champions_container,
                    headline="No champions yet.",
                    body="Go win some belts.",
                    icon_text="🏆",
                )
                empty.pack(side="top", fill="x", pady=SPACE_MD)
                self._champion_widgets.append(empty)
                return

            # Horizontal strip of champion chips. Wrap into rows of 4
            # max (so 8 champions = 2 rows of 4) using grid.
            strip = ctk.CTkFrame(self._champions_container, fg_color="transparent")
            strip.pack(side="top", fill="x")
            self._champion_widgets.append(strip)

            # 4-column grid; each cell = DataChip + HyperlinkLabel row.
            for i in range(4):
                strip.grid_columnconfigure(i, weight=1, uniform="champ")

            for idx, (wc_name, fighter_id, first, last) in enumerate(rows):
                row = idx // 4
                col = idx % 4
                cell = ctk.CTkFrame(strip, fg_color="transparent")
                cell.grid(row=row, column=col, sticky="ew",
                           padx=SPACE_XS, pady=SPACE_XS)
                self._champion_widgets.append(cell)

                # Inner card-like frame so each champion reads as a
                # discrete chip-pair.
                inner = ctk.CTkFrame(
                    cell,
                    fg_color=theme.colors.bg_card_elevated,
                    corner_radius=4,
                    border_width=1,
                    border_color=theme.colors.border_subtle,
                )
                inner.pack(fill="x", padx=2, pady=2)
                self._champion_widgets.append(inner)

                # Top row: DataChip (champion variant) with WC name.
                chip = DataChip(inner, text=wc_name or "CHAMP",
                                 variant="champion")
                chip.pack(side="top", anchor="w", padx=SPACE_SM,
                           pady=(SPACE_XS, 0))
                self._champion_widgets.append(chip)

                # Bottom row: champion name as HyperlinkLabel.
                champion_name = f"{first or ''} {last or ''}".strip()
                if fighter_id is not None and champion_name:
                    name_link = HyperlinkLabel(
                        inner, text=champion_name,
                        fighter_id=fighter_id,
                        font=theme.fonts.body,
                        anchor="w",
                    )
                    name_link.pack(side="top", anchor="w",
                                    padx=SPACE_SM, pady=(0, SPACE_XS))
                    self._champion_widgets.append(name_link)
                else:
                    name_label = ctk.CTkLabel(
                        inner, text="Vacant",
                        font=theme.fonts.body,
                        text_color=theme.colors.text_tertiary,
                        anchor="w",
                    )
                    name_label.pack(side="top", anchor="w",
                                     padx=SPACE_SM, pady=(0, SPACE_XS))
                    self._champion_widgets.append(name_label)
        except Exception as e:
            print(f"Warning: champions refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Fighter Watch (daily_headlines + fighter_descriptors — §17 cache)
    # ------------------------------------------------------------
    # PRESERVED queries (_lookup_fighter_watch_data, _find_hottest_
    # streak_fighter). NEW rendering: GradientCard + PortraitFrame +
    # MomentumRing + FormMeter. NEW query: _query_last_5_fights.

    def _refresh_fighter_watch(self, conn):
        """Render the three Fighter Watch cards (Section 5).

        Per D1+D3+D4:
          - Top Prospect: from daily_headlines.fastest_rising → fighter_id
            → fighter_descriptors.narrative_family voice phrase.
          - Hottest Streak: direct query of fighter_descriptors for
            momentum='very_high' (or 'high' fallback), EXCLUDING the
            Top Prospect fighter so the card shows a different face.
          - Biggest Fall: from daily_headlines.biggest_fall → fighter_id
            → fighter_descriptors.momentum voice phrase.

        Phase 2.5: each card = GradientCard wrapper (gold for Top
        Prospect + Hottest Streak, crimson for Biggest Fall) +
        PortraitFrame + name (HyperlinkLabel) + MomentumRing + voice
        phrase + FormMeter (last 5 fights W/L blocks).
        """
        try:
            self._destroy_widgets(self._watch_cards)
            self._watch_cards = []

            # PRESERVED: pull the latest headlines for fighter_id lookups.
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

            # ---- TOP PROSPECT card (gold gradient) ----
            top_prospect_data = self._lookup_fighter_watch_data(
                conn, fastest_rising)
            self._render_watch_card(
                self._watch_container, grid_col=0,
                title="TOP PROSPECT",
                data=top_prospect_data,
                default_voice="the wunderkind everyone's talking about",
                empty_voice="No prospect emerging yet.",
                is_falling=False,
                conn=conn,
            )

            # ---- HOTTEST STREAK card (gold gradient) ----
            # D3 — exclude top-prospect fighter.
            streak_fighter_id = self._find_hottest_streak_fighter(
                conn, exclude_ids={fastest_rising} if fastest_rising else set())
            streak_data = self._lookup_fighter_watch_data(
                conn, streak_fighter_id)
            self._render_watch_card(
                self._watch_container, grid_col=1,
                title="HOTTEST STREAK",
                data=streak_data,
                default_voice="riding a hot streak",
                empty_voice="No one's on a hot streak right now.",
                is_falling=False,
                conn=conn,
            )

            # ---- BIGGEST FALL card (crimson gradient) ----
            biggest_fall_data = self._lookup_fighter_watch_data(
                conn, biggest_fall)
            self._render_watch_card(
                self._watch_container, grid_col=2,
                title="BIGGEST FALL",
                data=biggest_fall_data,
                default_voice="in freefall",
                empty_voice="Nobody's sliding today.",
                is_falling=True,
                conn=conn,
            )
        except Exception as e:
            print(f"Warning: fighter-watch refresh failed: {e}", flush=True)

    def _lookup_fighter_watch_data(self, conn, fighter_id):
        """Look up a fighter's name + voice phrases for a watch card.

        PRESERVED from pre-Phase-2.5. Per D1+D4: reads from fighters
        (first_name/last_name only — NOT attributes) + fighter_descriptors
        (cache — momentum + narrative_family voice phrases). The
        "label||phrase" storage is decoded via decode_phrase (D4).

        Returns:
            dict with keys:
              fighter_id, name, momentum_phrase, narrative_phrase,
              momentum_label (the canonical label, for MomentumRing
              tier mapping — NEW for Phase 2.5).
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
                "fighter_id": fighter_id,
                "name": name,
                "momentum_phrase": decode_phrase(momentum_stored),
                "narrative_phrase": decode_phrase(narrative_stored),
                # NEW (Phase 2.5): the canonical momentum LABEL for
                # the MomentumRing tier mapping. We extract it from
                # the stored "label||phrase" string.
                "momentum_label": _decode_momentum_label(momentum_stored),
            }
        except sqlite3.Error as e:
            print(f"Warning: fighter lookup failed for id={fighter_id}: {e}",
                  flush=True)
            return None

    def _find_hottest_streak_fighter(self, conn, exclude_ids=None):
        """Find the fighter with the hottest momentum.

        PRESERVED from pre-Phase-2.5. Per D3: query fighter_descriptors
        for momentum='very_high' (or 'high' as fallback), EXCLUDING
        the given exclude_ids. Cached via query_cached.
        """
        exclude_ids = exclude_ids or set()
        try:
            for momentum_label in ("very_high", "high"):
                cache_key = f"hot_streak_{momentum_label}"
                rows = query_cached(
                    "dashboard", cache_key,
                    lambda label=momentum_label: conn.execute(
                        """
                        SELECT fd.fighter_id
                        FROM fighter_descriptors fd
                        JOIN fighters f ON f.fighter_id = fd.fighter_id
                        WHERE f.is_active = 1 AND f.is_retired = 0
                          AND SUBSTR(fd.momentum, 1,
                                     INSTR(fd.momentum || '||', '||') - 1) =?
                        ORDER BY fd.fighter_id ASC
                        """,
                        (label,),
                    ).fetchall(),
                )
                for (fid,) in rows:
                    if fid not in exclude_ids:
                        return fid
                if rows:
                    return rows[0][0]
        except sqlite3.Error as e:
            print(f"Warning: hottest-streak query failed: {e}",
                  flush=True)
        return None

    def _query_last_5_fights(self, conn, fighter_id):
        """Query the last 5 fight outcomes for a fighter (FormMeter data).

        NEW (Phase 2.5). Per D12: reads fight_history.outcome
        ('win'/'loss'/'draw'/'nc') for the given fighter, ordered by
        event_date DESC, LIMIT 5. Maps to 'W'/'L'/'D'/'D' (nc treated
        as draw for form visualization).

        Args:
            conn: SQLite connection.
            fighter_id: the fighter's DB id.

        Returns:
            List of 'W'/'L'/'D' strings (oldest first, so the FormMeter
            shows the streak chronologically left→right). Empty list if
            no fight history or fighter_id is None.
        """
        if fighter_id is None:
            return []
        try:
            rows = conn.execute(
                """
                SELECT outcome FROM fight_history
                WHERE fighter_id=?
                ORDER BY event_date DESC, fight_history_id DESC
                LIMIT 5
                """,
                (fighter_id,),
            ).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: last-5-fights query failed: {e}", flush=True)
            return []

        # rows is newest-first; reverse so the FormMeter shows oldest
        # on the left, newest on the right (standard "form" convention).
        mapping = {"win": "W", "loss": "L", "draw": "D", "nc": "D"}
        results = [mapping.get(str(r[0]).strip().lower(), "D")
                   for r in reversed(rows) if r[0]]
        return results

    def _render_watch_card(self, parent_row, grid_col, title, data,
                            default_voice, empty_voice, is_falling=False,
                            conn=None):
        """Render a single Fighter Watch card (Phase 2.5 redesign).

        REWRITTEN for Phase 2.5. Uses GradientCard (gold or crimson
        variant) as the wrapper. Composes inside it:
          - Eyebrow (title) at top
          - Middle row: 64px PortraitFrame + name (HyperlinkLabel) +
            MomentumRing (right-aligned)
          - Voice phrase (italic, centered) — prefer narrative_phrase,
            fall back to momentum_phrase, fall back to default_voice.
          - FormMeter (compact) showing last 5 fights W/L blocks
          - Context line (empty for now — the daily_headlines body
            could be used if available, but the watch cards query
            fighter_descriptors directly which doesn't have a context
            field. Future Phase 4+ can add this.)

        Args:
            parent_row: the grid container (self._watch_container).
            grid_col: the grid column index (0, 1, or 2).
            title: the card title (e.g., "TOP PROSPECT").
            data: dict from _lookup_fighter_watch_data, or None.
            default_voice: voice phrase to use if data has no
                narrative_phrase.
            empty_voice: voice phrase for the empty state (per D6).
            is_falling: True for the Biggest Fall card (crimson gradient).
            conn: SQLite connection (for the FormMeter's last-5-fights
                query). If None, no FormMeter is shown.
        """
        try:
            theme = get_theme()
            variant = "crimson" if is_falling else "gold"

            # ---- GradientCard wrapper ----
            card = GradientCard(
                parent_row, variant=variant,
                padding=SPACE_MD, corner_radius=6,
            )
            card.grid(row=0, column=grid_col, sticky="nsew",
                       padx=(SPACE_XS if grid_col == 1 else 0,
                             SPACE_XS if grid_col == 1 else 0),
                       pady=0)
            # Adjust padx for first/last column (no inner gap on the
            # outer edges).
            if grid_col == 0:
                card.grid_configure(padx=(0, SPACE_XS))
            elif grid_col == 2:
                card.grid_configure(padx=(SPACE_XS, 0))
            self._watch_cards.append(card)

            # ---- Eyebrow (title) ----
            eyebrow_color = (theme.colors.crimson if is_falling
                              else theme.colors.gold)
            eyebrow = ctk.CTkLabel(
                card.content_frame, text=title,
                font=theme.fonts.caption, text_color=eyebrow_color,
                anchor="w",
            )
            eyebrow.pack(side="top", fill="x", pady=(0, SPACE_SM))
            self._watch_cards.append(eyebrow)

            if data is None:
                # Empty state (D6).
                empty_label = ctk.CTkLabel(
                    card.content_frame, text=empty_voice,
                    font=theme.fonts.body_small,
                    text_color=theme.colors.text_tertiary,
                    anchor="w", wraplength=180, justify="left",
                )
                empty_label.pack(side="top", fill="x", pady=(0, SPACE_MD))
                self._watch_cards.append(empty_label)
                return

            fighter_id = data.get("fighter_id")
            name = data.get("name", "The fighter")
            momentum_label = data.get("momentum_label", "stable")

            # ---- Middle row: portrait + name/stats + momentum ring ----
            middle = ctk.CTkFrame(card.content_frame, fg_color="transparent")
            middle.pack(side="top", fill="x", pady=(0, SPACE_SM))
            self._watch_cards.append(middle)

            # 64px PortraitFrame (placeholder initials — no portrait
            # image asset wired up here; Phase 4+ can add it).
            initials = "".join([w[0] for w in name.split() if w])[:2].upper() or "?"
            portrait = PortraitFrame(
                middle, ctk_image=None, size="watch",
                is_champion=False, initials=initials,
                fighter_id=fighter_id,
            )
            portrait.pack(side="left", padx=(0, SPACE_SM))
            self._watch_cards.append(portrait)

            # Right side: name + stats + momentum ring.
            right = ctk.CTkFrame(middle, fg_color="transparent")
            right.pack(side="left", fill="x", expand=True)
            self._watch_cards.append(right)

            # Name (HyperlinkLabel — click navigates to Fighter Profile).
            if fighter_id is not None:
                name_label = HyperlinkLabel(
                    right, text=name, fighter_id=fighter_id,
                    font=(theme.fonts.h3[0], theme.fonts.h3[1], "bold"),
                    anchor="w", wraplength=140, justify="left",
                )
            else:
                name_label = ctk.CTkLabel(
                    right, text=name,
                    font=(theme.fonts.h3[0], theme.fonts.h3[1], "bold"),
                    text_color=theme.colors.text_primary,
                    anchor="w", wraplength=140, justify="left",
                )
            name_label.pack(side="top", anchor="w", pady=(0, SPACE_XS))
            self._watch_cards.append(name_label)

            # MomentumRing (right-aligned in the middle row, below the
            # name). The ring's tier comes from the fighter_descriptors
            # momentum label. Size 48px (smaller than default 64 so it
            # fits in the 4-col watch card).
            ring = MomentumRing(
                right, tier=momentum_label, size=48,
                show_label=True, thickness=5,
            )
            ring.pack(side="top", anchor="w", pady=(SPACE_XS, 0))
            self._watch_cards.append(ring)

            # ---- Voice phrase (italic, centered) ----
            voice = (data.get("narrative_phrase")
                     or data.get("momentum_phrase")
                     or default_voice)
            voice_label = ctk.CTkLabel(
                card.content_frame, text=title_case_phrase(voice),
                font=(theme.fonts.descriptor[0],
                      theme.fonts.descriptor[1], "italic"),
                text_color=theme.colors.text_primary,
                anchor="center", justify="center", wraplength=200,
            )
            voice_label.pack(side="top", fill="x", pady=(0, SPACE_SM))
            self._watch_cards.append(voice_label)

            # ---- FormMeter (last 5 fights W/L blocks) ----
            # NEW (Phase 2.5). Shows the fighter's last 5 fight outcomes
            # as gold (W) / crimson (L) / steel (D) blocks. Compact
            # variant (16×16 blocks) so it fits in the 4-col card.
            if conn is not None and fighter_id is not None:
                results = self._query_last_5_fights(conn, fighter_id)
                if results:
                    form = FormMeter(
                        card.content_frame, results=results,
                        compact=True, show_form_score=False,
                    )
                    form.pack(side="top", anchor="w", pady=(0, SPACE_XS))
                    self._watch_cards.append(form)

            # ---- "View Profile →" hyperlink (footer) ----
            if fighter_id is not None:
                view_link = HyperlinkLabel(
                    card.content_frame, text="View Profile →",
                    fighter_id=fighter_id,
                    font=theme.fonts.caption,
                    anchor="w",
                )
                view_link.pack(side="top", anchor="w", pady=(SPACE_XS, 0))
                self._watch_cards.append(view_link)
        except Exception as e:
            print(f"Warning: watch-card render failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Recent News (news_items — game-state news feed)
    # ------------------------------------------------------------
    # PRESERVED query. NEW rendering: NewsCard list + "View all" link.

    def _refresh_news(self, conn):
        """Render the Recent News list using NewsCard components.

        Per the Task 6.3 brief: "news_items is OK for display since it
        doesn't expose raw attribute values." We read the headline,
        body, topic, published_at, and fighter_id fields. The NewsCard
        component handles the layout (topic chip + headline + body +
        timestamp). Fighter-specific headlines render as HyperlinkLabels.

        Phase 2.5: 5 NewsCards stacked vertically + "View all" hyperlink
        at the bottom (no-op for now — the News Feed screen isn't built
        yet). If no news, EmptyState.
        """
        try:
            self._destroy_widgets(self._news_widgets)
            self._news_widgets = []

            theme = get_theme()

            # PRESERVED query — news_items, fighter_id included for
            # the HyperlinkLabel wiring.
            rows = []
            try:
                rows = conn.execute(
                    "SELECT headline, body, topic, published_at, fighter_id "
                    "FROM news_items "
                    "ORDER BY published_at DESC LIMIT 5"
                ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: news_items query failed: {e}",
                      flush=True)

            if not rows:
                # Empty state (D6).
                empty = EmptyState(
                    self._news_container,
                    headline="The newswire is quiet.",
                    body="No stories have broken in the last 24 hours. "
                         "Advance a day to see what develops.",
                    icon_text="📰",
                )
                empty.pack(side="top", fill="x", pady=SPACE_MD)
                self._news_widgets.append(empty)
                return

            # Render each news item as a NewsCard.
            for headline, body, topic, published_at, fighter_id in rows:
                # Truncate body to ~2 lines (~180 chars) for the card.
                body_text = body or ""
                if len(body_text) > 180:
                    body_text = body_text[:177].rstrip() + "..."

                news_card = NewsCard(
                    self._news_container,
                    topic=_topic_label(topic),
                    headline=headline or "(no headline)",
                    body=body_text,
                    timestamp=_format_date(published_at),
                    fighter_id=fighter_id if fighter_id else None,
                    has_detail=False,
                )
                news_card.pack(side="top", fill="x", pady=(0, SPACE_SM))
                self._news_widgets.append(news_card)

            # "View all ▶" hyperlink at the bottom (no-op — News Feed
            # screen not built yet).
            view_all = HyperlinkLabel(
                self._news_container, text="View all ▶",
                font=theme.fonts.caption,
                anchor="e",
            )
            view_all.pack(side="top", anchor="e", pady=(SPACE_SM, 0))
            self._news_widgets.append(view_all)
        except Exception as e:
            print(f"Warning: news refresh failed: {e}", flush=True)

    # ============================================================
    # HELPERS — widget lifecycle
    # ============================================================

    @staticmethod
    def _destroy_widgets(widget_list):
        """Destroy every widget in the list + clear the list.

        Used by every _refresh_* method to clear the old dynamic
        widgets before re-rendering (D8 + D10). Defensive — silently
        skips widgets that fail to destroy (already destroyed, etc.).
        """
        for w in widget_list:
            try:
                w.destroy()
            except Exception:
                pass
        widget_list.clear()
