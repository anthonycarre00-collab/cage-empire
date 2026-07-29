"""CAGE EMPIRE — Main CTk application shell (Stage 6 — Task 6.2).

The dual-mode CTk window with:
  - Top bar (60px): logo mark, sim date, cash, Advance Day button
  - Sidebar (180px collapsed / 240px expanded): 8 nav destinations
  - Main content (flexible): one screen at a time, scrollable
  - Bottom bar (32px): scrolling news ticker + next-event countdown

Per docs/GUI_PLAN.md §3.5:
  - Office Mode shell is the default
  - Fight Night Mode shell dims the sidebar + swaps the top bar
    button (Advance Day → Exit Fight) + adds transport controls
    to the bottom bar

CONVENTIONS compliance:
  §13 — Design Law: the shell is infrastructure supporting every
        pillar. The sidebar navigation groups screens by pillar
        (HOME = all pillars, FIGHTERS = Discovery/Investment/Growth,
        EVENTS = Conflict, BUSINESS = Empire Builder, WORLD =
        Kingmaker/Historian, SETTINGS = utility).
  §14 — Voice Layer: the shell displays sim date + cash in the top
        bar. These are NOT raw attribute values — they're game-state
        values (date, money) which are OK to display as numbers per
        §14 (which forbids raw FIGHTER ATTRIBUTE values, not game
        state).
  §15 — Event Bus: the shell's Advance Day button calls
        services.clock.advance_day(conn) which delegates to
        tick_processor.run_tick(conn) which publishes TICK_ADVANCED.
        The shell does NOT publish events itself.

Architecture:
  - CageEmpireApp(ctk.CTk): the main window
  - _build_top_bar(): logo + date + cash + Advance Day button
  - _build_sidebar(): 8 nav buttons with badge counts
  - _build_main_content(): scrollable frame for screen content
  - _build_bottom_bar(): news ticker + next-event countdown
  - _navigate(screen_name): switch screens via GameState
  - _on_advance_day(): call services.clock.advance_day + refresh_all
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

import customtkinter as ctk

# Set appearance + theme before creating the window
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Import after CTk setup so theme registration has a Tk root
from ui.theme import (
    OFFICE, FIGHT_NIGHT, CURRENT_THEME, set_theme, get_theme,
    LOGO_COMPACT, _register_fonts,
)
from ui.state import GameState, get_state

# Services (Task 6.0 extraction)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from services.clock import get_clock, advance_day
from services.news_svc import get_latest_news_summary

# Try to import Pillow for logo display
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ============================================================
# NAVIGATION CONFIG
# ============================================================

NAV_GROUPS = [
    ("HOME", [
        ("dashboard", "Dashboard", "home"),
        ("schedule", "Schedule", "calendar"),
        ("news", "News Feed", "news"),
    ]),
    ("FIGHTERS", [
        ("roster", "Roster", "roster"),
        ("free_agents", "Free Agents", "free_agents"),
        ("scouting", "Scouting", "scouting"),
        ("fighter_profile", "Fighter Profile", "fighter"),
        ("hall_of_fame", "Hall of Fame", "hof"),
    ]),
    ("EVENTS", [
        ("event_builder", "Event Builder", "event_builder"),
        ("matchmaking", "Matchmaking", "matchmaking"),
        ("fight_resolution", "Fight Resolution", "fight"),
        ("past_events", "Past Events", "past_events"),
    ]),
    ("BUSINESS", [
        ("finance", "Finance", "finance"),
        ("contracts", "Contracts", "contracts"),
        ("rival_promotions", "Rival Promotions", "rivals"),
        ("gyms", "Gyms", "gyms"),
    ]),
    ("WORLD", [
        ("rankings", "Rankings", "rankings"),
        ("titles", "Titles", "titles"),
        ("rivalries", "Rivalries", "rivalries"),
        ("records", "Records", "records"),
    ]),
    ("SETTINGS", [
        ("settings", "Settings", "settings"),
        ("save_load", "Save / Load", "save"),
        ("mods", "Mods", "mods"),
    ]),
]


class CageEmpireApp(ctk.CTk):
    """The main CAGE EMPIRE application window.

    Dual-mode: Office Mode (default) + Fight Night Mode (Fight
    Resolution screen only). The top bar + sidebar + bottom bar
    form the persistent shell; the main content area switches
    between 22 screens.
    """

    def __init__(self, db_path=None):
        super().__init__()

        # ============================================================
        # DB CONNECTION
        # ============================================================
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent / "data" / "cage_empire.db"
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA foreign_keys = ON;")

        # ============================================================
        # GAME STATE SINGLETON — player_promotion_id set AFTER
        # the player picks a promotion on the startup screen.
        # Default is None until selection.
        # ============================================================
        self.game_state = GameState(self.conn, player_promotion_id=None)

        # ============================================================
        # Stage 6 (Phase 1, Fix 1.2 + Fix 1.4): Register all 15
        # event-bus subscribers. Without this, no simulation runs on
        # Advance Day — no retirements, injuries, camps, scouting,
        # rival-AI, news, or auto-save. Copied from the old
        # App.__init__ (src/app.py:328-574). Fix 1.4 added #15
        # (hof_svc) so fighters who retire during gameplay are
        # inducted into the Hall of Fame (Historian fantasy).
        # ============================================================
        try:
            from news import register_subscribers as _register_news
            _register_news()
        except ImportError:
            pass  # news.py not available — legacy behavior
        try:
            from social import register_subscribers as _register_social
            _register_social()
        except ImportError:
            pass  # social.py not available — legacy behavior
        try:
            from rivalries import register_subscribers as _register_rivalries
            _register_rivalries()
        except ImportError:
            pass  # rivalries.py not available — legacy behavior
        try:
            from punditry import register_subscribers as _register_punditry
            _register_punditry()
        except ImportError:
            pass  # punditry.py not available — legacy behavior
        try:
            from morale import register_subscribers as _register_morale
            _register_morale()
        except ImportError:
            pass  # morale.py not available — legacy behavior
        try:
            from suspensions import register_subscribers as _register_suspensions
            _register_suspensions()
        except ImportError:
            pass  # suspensions.py not available — legacy behavior
        try:
            from agent_offers import register_subscribers as _register_agent_offers
            _register_agent_offers()
        except ImportError:
            pass  # agent_offers.py not available — legacy behavior
        try:
            from career_arc import register_subscribers as _register_career_arc
            _register_career_arc()
        except ImportError:
            pass  # career_arc.py not available — legacy behavior
        try:
            from rival_ai import register_subscribers as _register_rival_ai
            _register_rival_ai()
        except ImportError:
            pass  # rival_ai.py not available — legacy behavior
        try:
            from show_rating import register_subscribers as _register_show_rating
            _register_show_rating()
        except ImportError:
            pass  # show_rating.py not available — legacy behavior
        try:
            from venues import register_subscribers as _register_venues
            _register_venues()
        except ImportError:
            pass  # venues.py not available — legacy behavior
        try:
            from save_load import register_subscribers as _register_save_load
            _register_save_load()
        except ImportError:
            pass  # save_load.py not available — legacy behavior
        try:
            from player_settings import register_subscribers as _register_player_settings
            _register_player_settings()
        except ImportError:
            pass  # player_settings.py not available — legacy behavior
        try:
            from reputation import register_subscribers as _register_reputation
            _register_reputation()
        except ImportError:
            pass  # reputation.py not available — legacy behavior
        # Phase 1 — Fix 1.4: Hall of Fame induction subscriber.
        # Subscribes to FIGHTER_RETIRED and inducts qualifying
        # fighters into hall_of_fame. Without this, the 60 seeded
        # legends are the only HoF inductees forever — every champion
        # the player develops would be forgotten on retirement
        # (Historian fantasy collapse). Lazy import for the same
        # reasons as the 14 modules above.
        try:
            from services.hof_svc import register_subscribers as _register_hof
            _register_hof()
        except ImportError:
            pass  # services/hof_svc.py not available — legacy behavior
        # Phase 2 (Task 2.1-snapshot-cache): Interpretation layer
        # event-bus subscribers. Subscribes to 4 events
        # (FIGHT_RESOLVED, FIGHTER_RETIRED, TITLE_CHANGED,
        # CONTRACT_EXPIRED) for targeted single-fighter snapshot
        # refresh. Registered LAST per CONVENTIONS §17.5 — the
        # interpretation layer must run after every simulation-side
        # subscriber has finished so the cache reflects the latest
        # simulation state. The full daily pass is NOT a subscriber —
        # it runs as a POST-COMMIT step in tick_processor.run_tick.
        try:
            from interpretation import register_subscribers as _register_interpretation
            _register_interpretation()
        except ImportError:
            pass  # interpretation/ package not available yet

        # ============================================================
        # WINDOW SETUP
        # ============================================================
        self.title("CAGE EMPIRE")
        self.geometry("1400x900")
        self.minsize(1200, 800)

        # Register fonts now that we have a Tk root
        _register_fonts()

        # ============================================================
        # BUILD UI SHELL
        # ============================================================
        self._build_top_bar()
        self._build_sidebar()
        self._build_main_content()
        self._build_bottom_bar()

        # ============================================================
        # Phase 1 — Fix 1.3: Register the Save/Load screen.
        # The screen is created with self.screen_container as its
        # parent (so it packs into the main content area). It is NOT
        # packed yet — _navigate("save_load") packs it when the
        # player clicks the sidebar entry. The screen's refresh
        # callback is _refresh (re-queries list_saves() + re-renders
        # the list). Registered with GameState so set_active_screen
        # works + so refresh_all() picks it up after Save/Load.
        # ============================================================
        from ui.screens.save_load import SaveLoadScreen
        self.save_load_screen = SaveLoadScreen(self.screen_container)
        self.game_state.register_screen(
            "save_load", self.save_load_screen, self.save_load_screen._refresh
        )

        # ============================================================
        # Stage 6 — Task 6.3: Register the Dashboard screen.
        # The Dashboard is the player's home screen — the FIRST real
        # screen in CAGE EMPIRE (every prior screen is a placeholder).
        # Created with self.screen_container as its parent. Packed
        # by _navigate("dashboard") when the player clicks the
        # sidebar entry (or on app launch — see _navigate call below).
        # The refresh callback (_refresh) re-queries daily_headlines,
        # fighter_descriptors, promotions, titles, news_items + re-
        # renders every section. Registered with GameState so:
        #   - set_active_screen("dashboard") triggers _refresh on nav.
        #   - refresh_all() picks it up after Advance Day / Save /
        #     Load / theme toggle.
        # Per CONVENTIONS §17: reads from cache tables
        # (daily_headlines, fighter_descriptors) for fighter
        # interpretation data + game-state tables (promotions, titles,
        # fighters, news_items) for non-fighter data. NEVER reads
        # fighter_attributes / fighter_personality / fighter_career.
        # ============================================================
        from ui.screens.dashboard import DashboardScreen
        self.dashboard_screen = DashboardScreen(self.screen_container)
        self.game_state.register_screen(
            "dashboard", self.dashboard_screen, self.dashboard_screen._refresh
        )

        # ============================================================
        # Stage 6 — Task 6.4: Register the Roster + Fighter Profile
        # screens. These are the two highest-traffic Office Mode
        # screens — the player spends most of their time here. Both
        # are registered with GameState so:
        #   - set_active_screen("roster") triggers _refresh on nav.
        #   - set_active_screen("fighter_profile") triggers _refresh
        #     on nav.
        #   - refresh_all() picks them up after Advance Day / Save /
        #     Load / theme toggle.
        # Per CONVENTIONS §17: both screens read from cache tables
        # (fighter_descriptors) for fighter interpretation data +
        # game-state tables (fighters, weight_classes, gyms,
        # promotions, fighter_career, fight_history, fighter_bios,
        # titles) for non-attribute data. NEVER read from
        # fighter_attributes / fighter_personality.
        #
        # The Fighter Profile screen needs to know WHICH fighter to
        # display. The Roster calls
        # `fighter_profile_screen.set_fighter_id(fighter_id)` BEFORE
        # calling state.set_active_screen("fighter_profile"). The
        # Fighter Profile screen stores the fighter_id + renders it
        # on _refresh().
        # ============================================================
        from ui.screens.roster import RosterScreen
        self.roster_screen = RosterScreen(self.screen_container)
        self.game_state.register_screen(
            "roster", self.roster_screen, self.roster_screen._refresh
        )

        from ui.screens.fighter_profile import FighterProfileScreen
        self.fighter_profile_screen = FighterProfileScreen(self.screen_container)
        self.game_state.register_screen(
            "fighter_profile", self.fighter_profile_screen,
            self.fighter_profile_screen._refresh
        )

        # ============================================================
        # Stage 6 — Task 6.5: Register the Free Agents + Scouting
        # screens. These complete the FIGHTERS group alongside the
        # Roster + Fighter Profile (Task 6.4). Both are registered
        # with GameState so:
        #   - set_active_screen("free_agents") triggers _refresh on
        #     nav — re-queries the unsigned-fighter pool.
        #   - set_active_screen("scouting") triggers _refresh on nav
        #     — re-queries scouting_reports + the scout list.
        #   - refresh_all() picks them up after Advance Day / Save /
        #     Load / theme toggle / fighter-signed / scout-assigned.
        # Per CONVENTIONS §17: both screens read from cache tables
        # (fighter_descriptors) for fighter interpretation data +
        # game-state tables (fighters, weight_classes, fighter_career,
        # scouting_reports, staff) for non-attribute data. NEVER read
        # from fighter_attributes / fighter_personality.
        #
        # The Free Agents screen's Sign button calls
        # `services.contracts.sign_free_agent(conn, fighter_id,
        # promotion_id, start_date)` which writes a contract row +
        # flips the fighter's current_promotion_id + writes a signing
        # news item + publishes Events.FIGHTER_SIGNED. The Scouting
        # screen's Assign Scout button calls
        # `scouting.assign_scout(conn, scout_id, target_fighter_id,
        # promotion_id)` which stores the assignment in the scout's
        # specialty JSON — the report itself is generated 7 ticks
        # later by _check_scouting_assignments on each tick.
        # ============================================================
        from ui.screens.free_agents import FreeAgentsScreen
        self.free_agents_screen = FreeAgentsScreen(self.screen_container)
        self.game_state.register_screen(
            "free_agents", self.free_agents_screen,
            self.free_agents_screen._refresh
        )

        from ui.screens.scouting import ScoutingScreen
        self.scouting_screen = ScoutingScreen(self.screen_container)
        self.game_state.register_screen(
            "scouting", self.scouting_screen,
            self.scouting_screen._refresh
        )

        # ============================================================
        # SHOW PROMOTION SELECTION SCREEN FIRST
        # The player chooses which promotion to manage.
        # Only after selection do we navigate to the Dashboard.
        # ============================================================
        self._show_promotion_select()

    def _show_promotion_select(self):
        """Show the promotion selection screen at startup."""
        theme = get_theme()

        # Hide the top bar + sidebar + bottom bar until a promotion is chosen
        self.top_bar.pack_forget()
        self.sidebar.pack_forget()
        self.bottom_bar.pack_forget()

        # Clear main content
        for widget in self.screen_container.winfo_children():
            widget.destroy()

        # Create the promotion selection screen
        from ui.screens.promotion_select import PromotionSelectScreen
        self.promo_select_screen = PromotionSelectScreen(
            self.screen_container,
            on_select_callback=self._on_promotion_selected,
            fg_color=theme.colors.bg_base,
        )
        self.promo_select_screen.set_conn(self.conn)
        self.promo_select_screen.pack(fill="both", expand=True)

    def _on_promotion_selected(self, promotion_id):
        """Called when the player picks a promotion on the startup screen."""
        # Set the player's promotion in GameState
        self.game_state.player_promotion_id = promotion_id

        # Remove the promotion selection screen
        self.promo_select_screen.pack_forget()

        # Show the top bar + sidebar + bottom bar
        theme = get_theme()
        self.top_bar.pack(side="top", fill="x")
        self.sidebar.pack(side="left", fill="y")
        self.bottom_bar.pack(side="bottom", fill="x")

        # Navigate to the dashboard
        self._navigate("dashboard")
        self._update_top_bar()
        self._update_bottom_bar()

    # ============================================================
    # TOP BAR
    # ============================================================

    def _build_top_bar(self):
        """Build the 60px top bar: logo + date + cash + Advance Day."""
        theme = get_theme()
        self.top_bar = ctk.CTkFrame(self, height=60,
                                     corner_radius=0,
                                     fg_color=theme.colors.bg_surface)
        self.top_bar.pack(side="top", fill="x")
        self.top_bar.pack_propagate(False)

        # Logo (compact version)
        self.logo_label = ctk.CTkLabel(self.top_bar, text="CAGE EMPIRE",
                                        font=theme.fonts.h2,
                                        text_color=theme.colors.gold)
        self.logo_label.pack(side="left", padx=20)

        if HAS_PIL and LOGO_COMPACT.exists():
            try:
                img = Image.open(str(LOGO_COMPACT))
                img = img.resize((40, 40), Image.LANCZOS)
                self.logo_image = ctk.CTkImage(light_image=img, dark_image=img,
                                                size=(40, 40))
                self.logo_label.configure(image=self.logo_image,
                                           compound="left", text="")
            except Exception:
                pass  # fall back to text

        # Sim date (center-left)
        self.date_label = ctk.CTkLabel(self.top_bar, text="",
                                        font=theme.fonts.body,
                                        text_color=theme.colors.text_secondary)
        self.date_label.pack(side="left", padx=30)

        # Cash (center-right)
        self.cash_label = ctk.CTkLabel(self.top_bar, text="",
                                        font=theme.fonts.mono,
                                        text_color=theme.colors.gold)
        self.cash_label.pack(side="right", padx=20)

        # Advance Day button (the dopamine button — gold accent on hover)
        self.advance_button = ctk.CTkButton(self.top_bar,
                                             text="▶ Advance Day",
                                             font=theme.fonts.h3,
                                             width=140, height=36,
                                             corner_radius=8,
                                             fg_color=theme.colors.gold,
                                             hover_color=theme.colors.crimson,
                                             text_color=theme.colors.bg_base,
                                             command=self._on_advance_day)
        self.advance_button.pack(side="right", padx=20)

        self._update_top_bar()

    def _update_top_bar(self):
        """Refresh the date + cash display from the DB."""
        try:
            clock = get_clock(self.conn)
            if clock:
                date_str = clock[0]  # current_date
                week = clock[3]      # current_week
                year = clock[5]      # current_year
                if year == 0:
                    year = 1
                self.date_label.configure(
                    text=f"{date_str}  ·  Week {week}, Year {year}"
                )

            # Get player promotion cash
            promo_id = self.game_state.get_player_promotion_id()
            if promo_id is None:
                self.cash_label.configure(text="")
                return
            cash_row = self.conn.execute(
                "SELECT current_cash FROM promotions WHERE promotion_id=?",
                (promo_id,)
            ).fetchone()
            if cash_row:
                cash = cash_row[0]
                # Format as $X.XM
                if abs(cash) >= 1_000_000:
                    cash_str = f"${cash / 1_000_000:.1f}M"
                elif abs(cash) >= 1_000:
                    cash_str = f"${cash / 1_000:.0f}K"
                else:
                    cash_str = f"${cash:,.0f}"
                self.cash_label.configure(text=cash_str)
        except Exception as e:
            print(f"Warning: top bar update failed: {e}", flush=True)

    # ============================================================
    # SIDEBAR
    # ============================================================

    def _build_sidebar(self):
        """Build the 220px sidebar with nav groups."""
        theme = get_theme()
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0,
                                     fg_color=theme.colors.bg_surface)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Scrollable sidebar in case nav is too long
        sidebar_scroll = ctk.CTkScrollableFrame(self.sidebar,
                                                 fg_color="transparent",
                                                 scrollbar_button_color=theme.colors.bg_border)
        sidebar_scroll.pack(fill="both", expand=True)

        self.nav_buttons = {}
        for group_name, screens in NAV_GROUPS:
            # Group label
            group_label = ctk.CTkLabel(sidebar_scroll, text=group_name,
                                        font=theme.fonts.caption,
                                        text_color=theme.colors.text_tertiary)
            group_label.pack(anchor="w", padx=15, pady=(20, 8))

            for screen_name, display_name, icon_key in screens:
                btn = ctk.CTkButton(sidebar_scroll,
                                    text=display_name,
                                    font=theme.fonts.body_small,
                                    anchor="w",
                                    height=34,
                                    corner_radius=6,
                                    fg_color="transparent",
                                    hover_color=theme.colors.bg_surface_elevated,
                                    text_color=theme.colors.text_secondary,
                                    command=lambda sn=screen_name: self._navigate(sn))
                btn.pack(fill="x", padx=8, pady=2)
                self.nav_buttons[screen_name] = btn

    def _update_sidebar(self):
        """Highlight the active nav button."""
        theme = get_theme()
        active = self.game_state.get_active_screen()
        for name, btn in self.nav_buttons.items():
            if name == active:
                btn.configure(fg_color=theme.colors.bg_surface_elevated,
                              text_color=theme.colors.text_primary)
            else:
                btn.configure(fg_color="transparent",
                              text_color=theme.colors.text_secondary)

    # ============================================================
    # MAIN CONTENT
    # ============================================================

    def _build_main_content(self):
        """Build the scrollable main content area."""
        theme = get_theme()
        self.main_content = ctk.CTkFrame(self, corner_radius=0,
                                          fg_color=theme.colors.bg_base)
        self.main_content.pack(side="left", fill="both", expand=True)

        # Screen container — screens pack into this
        self.screen_container = ctk.CTkFrame(self.main_content, fg_color="transparent")
        self.screen_container.pack(fill="both", expand=True, padx=20, pady=20)

        # Placeholder label (shown until a screen is loaded)
        self.placeholder = ctk.CTkLabel(self.screen_container,
                                         text="Loading...",
                                         font=theme.fonts.h1,
                                         text_color=theme.colors.text_secondary)
        self.placeholder.pack(expand=True)

    def _navigate(self, screen_name):
        """Navigate to a screen.

        For "dashboard" (Stage 6 — Task 6.3): pack the registered
        DashboardScreen into the screen container. The refresh
        callback fires via state.set_active_screen below (which
        calls _refresh — re-queries daily_headlines, fighter_
        descriptors, promotions, titles, news_items + re-renders
        every section). The DashboardScreen instance is preserved
        across navigations (pack_forget on navigate-away, pack on
        navigate-to) so its rendered widgets survive — same pattern
        as SaveLoadScreen.

        For "save_load" (Phase 1 — Fix 1.3): pack the registered
        SaveLoadScreen into the screen container + call its refresh
        callback. The SaveLoadScreen instance is preserved across
        navigations (pack_forget on navigate-away, pack on
        navigate-to) so its state (cached save rows, entry value)
        survives.

        For "roster" + "fighter_profile" (Stage 6 — Task 6.4): pack
        the registered RosterScreen / FighterProfileScreen into the
        screen container + call its refresh callback. Both instances
        are preserved across navigations (pack_forget on navigate-
        away, pack on navigate-to) so the player's Roster pagination
        state + selected Fighter Profile survive a back-and-forth.
        The Fighter Profile screen's fighter_id is set BEFORE
        navigation via `fighter_profile_screen.set_fighter_id(id)`
        (called by RosterScreen._on_row_double_click).

        For "free_agents" + "scouting" (Stage 6 — Task 6.5): pack
        the registered FreeAgentsScreen / ScoutingScreen into the
        screen container + call its refresh callback. Both instances
        are preserved across navigations (pack_forget on navigate-
        away, pack on navigate-to) so the player's Free Agents
        pagination state + Scouting scroll position survive a back-
        and-forth. The Free Agents screen's Sign button calls
        services.contracts.sign_free_agent + state.refresh_all so
        the Roster + Dashboard reflect the new signing immediately.

        For other screens (placeholder until Tasks 6.6-6.14): show
        a placeholder label with the screen name.
        """
        theme = get_theme()

        # Clear current content. The DashboardScreen + SaveLoadScreen
        # + RosterScreen + FighterProfileScreen + FreeAgentsScreen +
        # ScoutingScreen are special — pack_forget them (don't
        # destroy) so their state survives across navigations.
        # Everything else (placeholders, future screens) is destroyed.
        dashboard_screen = getattr(self, "dashboard_screen", None)
        save_load_screen = getattr(self, "save_load_screen", None)
        roster_screen = getattr(self, "roster_screen", None)
        fighter_profile_screen = getattr(self, "fighter_profile_screen", None)
        free_agents_screen = getattr(self, "free_agents_screen", None)
        scouting_screen = getattr(self, "scouting_screen", None)
        preserved_screens = {
            dashboard_screen, save_load_screen,
            roster_screen, fighter_profile_screen,
            free_agents_screen, scouting_screen,
        }
        for widget in self.screen_container.winfo_children():
            if widget in preserved_screens:
                widget.pack_forget()
            else:
                widget.destroy()

        if screen_name == "dashboard" and dashboard_screen is not None:
            # Pack the DashboardScreen into the container. The refresh
            # callback fires via state.set_active_screen below.
            dashboard_screen.pack(fill="both", expand=True)
        elif screen_name == "save_load" and save_load_screen is not None:
            # Pack the SaveLoadScreen into the container. The refresh
            # callback fires via state.set_active_screen below.
            save_load_screen.pack(fill="both", expand=True)
        elif screen_name == "roster" and roster_screen is not None:
            # Pack the RosterScreen into the container. The refresh
            # callback fires via state.set_active_screen below.
            roster_screen.pack(fill="both", expand=True)
        elif (screen_name == "fighter_profile"
              and fighter_profile_screen is not None):
            # Pack the FighterProfileScreen into the container. The
            # refresh callback fires via state.set_active_screen below.
            # The fighter_id was set BEFORE navigation by the Roster's
            # _on_row_double_click handler — the screen is already
            # rendered with the right fighter.
            fighter_profile_screen.pack(fill="both", expand=True)
        elif (screen_name == "free_agents"
              and free_agents_screen is not None):
            # Pack the FreeAgentsScreen into the container. The refresh
            # callback fires via state.set_active_screen below — re-
            # queries the unsigned-fighter pool with the current
            # filter + search + pagination state preserved.
            free_agents_screen.pack(fill="both", expand=True)
        elif (screen_name == "scouting"
              and scouting_screen is not None):
            # Pack the ScoutingScreen into the container. The refresh
            # callback fires via state.set_active_screen below — re-
            # queries scouting_reports + the scout list.
            scouting_screen.pack(fill="both", expand=True)
        else:
            # Show placeholder with screen name
            label = ctk.CTkLabel(self.screen_container,
                                 text=f"[ {screen_name.replace('_', ' ').title()} ]\n\n"
                                      f"This screen will be implemented in a future task.\n"
                                      f"Theme: {theme.name}  ·  DB: {self.db_path.name}",
                                 font=theme.fonts.h1,
                                 text_color=theme.colors.text_secondary,
                                 justify="center")
            label.pack(expand=True)

        # Update state — this calls set_active_screen which calls
        # the screen's refresh callback (DashboardScreen._refresh
        # for "dashboard", SaveLoadScreen._refresh for "save_load",
        # RosterScreen._refresh for "roster", FighterProfileScreen.
        # _refresh for "fighter_profile").
        # For unregistered screens (every screen OTHER than these
        # four), this raises ValueError. We catch + ignore for the
        # placeholder screens — they have no refresh callback anyway.
        try:
            self.game_state.set_active_screen(screen_name)
        except ValueError:
            # Screen not registered (placeholder). Update active
            # screen name directly so the sidebar highlight works.
            self.game_state._active_screen = screen_name
        self._update_sidebar()
        self._update_top_bar()

    # ============================================================
    # BOTTOM BAR
    # ============================================================

    def _build_bottom_bar(self):
        """Build the 32px bottom bar: news ticker + next event."""
        theme = get_theme()
        self.bottom_bar = ctk.CTkFrame(self, height=32, corner_radius=0,
                                        fg_color=theme.colors.bg_surface)
        self.bottom_bar.pack(side="bottom", fill="x")
        self.bottom_bar.pack_propagate(False)

        self.ticker_label = ctk.CTkLabel(self.bottom_bar,
                                          text="CAGE EMPIRE · Loading news...",
                                          font=theme.fonts.caption,
                                          text_color=theme.colors.text_tertiary,
                                          anchor="w")
        self.ticker_label.pack(side="left", fill="x", expand=True, padx=15)

        self._update_bottom_bar()

    def _update_bottom_bar(self):
        """Refresh the news ticker from the DB."""
        try:
            from services.news_svc import get_latest_news_summary
            summary = get_latest_news_summary(self.conn, limit=3)
            if summary:
                text = "  ·  ".join(summary)
                if len(text) > 120:
                    text = text[:117] + "..."
                self.ticker_label.configure(text=text)
            else:
                self.ticker_label.configure(text="CAGE EMPIRE · No recent news")
        except Exception:
            self.ticker_label.configure(text="CAGE EMPIRE")

    # ============================================================
    # ACTIONS
    # ============================================================

    def _on_advance_day(self):
        """Advance Day button handler.

        Calls services.clock.advance_day (which delegates to
        tick_processor.run_tick), then refreshes all screens.
        """
        try:
            advance_day(self.conn)
            self.conn.commit()
            self.game_state.refresh_all()
            self._update_top_bar()
            self._update_bottom_bar()
        except Exception as e:
            print(f"Warning: advance_day failed: {e}", flush=True)

    # ============================================================
    # CLEANUP
    # ============================================================

    def destroy(self):
        """Clean up on window close — auto-save first (Phase 1, Fix 1.3).

        Saves the current game as 'exit_save' BEFORE closing the
        conn. This is a safety net — accidental closes (window X
        button, Alt+F4, system shutdown) won't lose progress. The
        player can load 'exit_save' from the Save/Load screen on
        next launch.

        Defensive — if the save fails (disk full, permission denied,
        broken conn), the failure is logged to stdout but the close
        still proceeds. We never block the window close on a save
        failure.
        """
        try:
            if self.conn:
                from save_load import save_game
                try:
                    save_game(self.conn, save_name="exit_save")
                except Exception as e:
                    # Save failure is non-fatal — log + continue so
                    # the window close isn't blocked.
                    print(f"Warning: exit auto-save failed: {e}",
                          flush=True)
                self.conn.close()
        except Exception as e:
            print(f"Warning: destroy cleanup failed: {e}", flush=True)
        super().destroy()


# ============================================================
# LAUNCHER
# ============================================================

def main():
    """Launch the CAGE EMPIRE app."""
    app = CageEmpireApp()
    app.mainloop()


if __name__ == "__main__":
    main()
