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
        # GAME STATE SINGLETON
        # ============================================================
        self.state = GameState(self.conn, player_promotion_id=1)

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
        self.state.register_screen(
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
        self.state.register_screen(
            "dashboard", self.dashboard_screen, self.dashboard_screen._refresh
        )

        # ============================================================
        # START ON DASHBOARD
        # ============================================================
        self._navigate("dashboard")

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
                self.date_label.configure(
                    text=f"{date_str}  ·  Week {week}, Year {year}"
                )

            # Get player promotion cash
            promo_id = self.state.get_player_promotion_id()
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
        """Build the 180px sidebar with 8 nav groups."""
        theme = get_theme()
        self.sidebar = ctk.CTkFrame(self, width=180, corner_radius=0,
                                     fg_color=theme.colors.bg_surface)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.nav_buttons = {}
        for group_name, screens in NAV_GROUPS:
            # Group label
            group_label = ctk.CTkLabel(self.sidebar, text=group_name,
                                        font=theme.fonts.caption,
                                        text_color=theme.colors.text_tertiary)
            group_label.pack(anchor="w", padx=15, pady=(15, 5))

            for screen_name, display_name, icon_key in screens:
                btn = ctk.CTkButton(self.sidebar,
                                    text=display_name,
                                    font=theme.fonts.body_small,
                                    anchor="w",
                                    height=32,
                                    corner_radius=6,
                                    fg_color="transparent",
                                    hover_color=theme.colors.bg_surface_elevated,
                                    text_color=theme.colors.text_secondary,
                                    command=lambda sn=screen_name: self._navigate(sn))
                btn.pack(fill="x", padx=5, pady=1)
                self.nav_buttons[screen_name] = btn

    def _update_sidebar(self):
        """Highlight the active nav button."""
        theme = get_theme()
        active = self.state.get_active_screen()
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

        For other screens (placeholder until Tasks 6.4-6.14): show
        a placeholder label with the screen name.
        """
        theme = get_theme()

        # Clear current content. The DashboardScreen + SaveLoadScreen
        # are special — pack_forget them (don't destroy) so their
        # state survives across navigations. Everything else
        # (placeholders, future screens) is destroyed.
        dashboard_screen = getattr(self, "dashboard_screen", None)
        save_load_screen = getattr(self, "save_load_screen", None)
        for widget in self.screen_container.winfo_children():
            if widget is dashboard_screen or widget is save_load_screen:
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
        # for "dashboard", SaveLoadScreen._refresh for "save_load").
        # For unregistered screens (every screen OTHER than
        # dashboard + save_load), this raises ValueError. We catch
        # + ignore for the placeholder screens — they have no
        # refresh callback anyway.
        try:
            self.state.set_active_screen(screen_name)
        except ValueError:
            # Screen not registered (placeholder). Update active
            # screen name directly so the sidebar highlight works.
            self.state._active_screen = screen_name
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
                                          text_color=theme.colors.text_tertiary)
        self.ticker_label.pack(side="left", padx=15)

        self._update_bottom_bar()

    def _update_bottom_bar(self):
        """Refresh the news ticker from the DB."""
        try:
            summary = get_latest_news_summary(self.conn, limit=3)
            if summary:
                self.ticker_label.configure(text="  ·  ".join(summary))
            else:
                self.ticker_label.configure(text="CAGE EMPIRE · No recent news")
        except Exception as e:
            self.ticker_label.configure(text=f"CAGE EMPIRE · News unavailable")

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
            self.state.refresh_all()
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
