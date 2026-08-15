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
import calendar
from pathlib import Path
from datetime import datetime

import customtkinter as ctk

# Set appearance + theme before creating the window.
# UI-REDESIGN-DASH-V2 Fix #1: removed ctk.set_default_color_theme(
# "dark-blue") — that line loaded CTk's built-in dark-blue theme,
# which OVERRIDES our custom OfficeColors palette for any widget
# that doesn't explicitly pass fg_color=. The result: buttons looked
# default-blue, frames looked default-grey, and the app felt "dull"
# no matter how much we tweaked OfficeColors. We now install our
# OWN cage_empire_theme.json (matching OfficeColors) — see
# theme.py:install_ctk_theme().
ctk.set_appearance_mode("dark")

# Import after CTk setup so theme registration has a Tk root
from ui.theme import (
    OFFICE, FIGHT_NIGHT, CURRENT_THEME, set_theme, get_theme,
    LOGO_COMPACT, _register_fonts, install_ctk_theme,
)
from ui.state import GameState, get_state

# Install our custom CTk theme (gold buttons, bg_card frames, gold
# progress bars — every widget defaults to our branded colors).
# CRITICAL FIX (per Claude's 2nd-opinion review, Task THEME-FONT-FIX-V3):
# Check the return value + raise loudly if the theme fails to load.
# The prior code called install_ctk_theme() as a bare statement,
# discarding the boolean. If the theme failed to load, the only signal
# was a print() to stdout — which the user might never see if launching
# via double-click. Now we raise RuntimeError, which will crash the app
# with a clear error message. This kills the 'is it even trying'
# ambiguity forever.
_theme_ok = install_ctk_theme()
if not _theme_ok:
    # The theme failed to load. DO NOT silently continue — that would
    # cause the user to see CTk's default blue theme + wonder why
    # 'nothing changed'. Crash with a clear error message instead.
    raise RuntimeError(
        "CAGE EMPIRE CTk theme failed to load. The app cannot continue "
        "with the default blue theme. Check the console output above "
        "for the specific error (JSON parse error, file not found, etc.)."
    )

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

# UI Fix Plan 2 — Phase 3, Fix 2 (voice renames):
# Display names updated to match the CAGE EMPIRE gritty
# journalism voice per the plan's Voice Recommendations table.
# The screen_name KEYS are unchanged ("dashboard", "roster", etc.)
# so every state.set_active_screen call, refresh registration, and
# nav button command continues to work without code changes —
# only the player-visible label text is renamed.
NAV_GROUPS = [
    ("HOME", [
        ("dashboard", "The Empire", "home"),
        ("schedule", "Calendar", "calendar"),
        ("news", "The Wire", "news"),
    ]),
    # UI Fix Plan 2 — Phase 1, Fix 18 (AD-3): "Fighter Profile"
    # removed from the FIGHTERS nav group. The screen stays
    # registered with GameState (so set_active_screen + refresh_all
    # work) + the _navigate("fighter_profile") branch still works
    # programmatically — the player reaches it via hyperlinks from
    # the Roster, Free Agents, Dashboard, etc. (Phase 3 fixes 7 +
    # 13 will install those hyperlinks). This declutters the sidebar
    # (Fighter Profile is a destination, not a starting point) +
    # matches the AD-3 architecture decision: "Accessible only via
    # hyperlinks from Roster, Open Market, Dashboard, etc."
    ("FIGHTERS", [
        ("roster", "The Stable", "roster"),
        ("free_agents", "Open Market", "free_agents"),
        ("scouting", "Scouting", "scouting"),
        ("hall_of_fame", "Legends", "hof"),
    ]),
    ("EVENTS", [
        ("event_builder", "Build a Card", "event_builder"),
        ("matchmaking", "Matchmaking", "matchmaking"),
        ("fight_resolution", "Fight Night", "fight"),
        ("past_events", "The Archive", "past_events"),
    ]),
    ("BUSINESS", [
        ("finance", "The Books", "finance"),
        ("contracts", "Deals", "contracts"),
        ("rival_promotions", "The Competition", "rivals"),
        ("gyms", "Training Camps", "gyms"),
    ]),
    ("WORLD", [
        ("rankings", "The Rankings", "rankings"),
        ("titles", "Belts", "titles"),
        ("rivalries", "Bad Blood", "rivalries"),
        ("records", "The Record Book", "records"),
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

        # DB Pruning service (REPLAN_RESET §10): runs monthly on the 1st,
        # prunes old news/headlines/social/injuries/camps to prevent DB bloat.
        # Must be registered AFTER all other subscribers so it doesn't prune
        # data that other subscribers still need to process on the same tick.
        try:
            from services.pruning_svc import register_subscribers as _register_pruning
            _register_pruning()
        except ImportError:
            pass  # services/pruning_svc.py not available — legacy behavior

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

        # CRITICAL: Wire the navigate callback so set_active_screen
        # (called by HyperlinkLabel, go_back, etc.) actually PACKS
        # the screen into the container. Without this, hyperlinks
        # refresh data but never show the screen.
        self.game_state.set_navigate_callback(self._navigate)

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
        # TICK-REENGINEER (Fix 2, PERF_ARCH_AUDIT §4.1) — Dashboard
        # per-section dirty-flag event subscribers.
        #
        # The Dashboard's _refresh used to destroy + rebuild ALL 9
        # sections on every call (~380 ms of widget work). On intra-
        # screen navigation (player returns to Dashboard from Roster),
        # nothing has actually changed — the headlines, champions,
        # fighter_watch, recent_results, news, etc. are all identical
        # to the last Dashboard render.
        #
        # The fix: per-section dirty flags. Event subscribers mark
        # specific sections dirty when a relevant event fires. The
        # next _refresh() only rebuilds the dirty sections.
        #
        # Section-to-event mapping (per PERF_ARCH_AUDIT §4.1):
        #   FIGHT_RESOLVED    → fighter_watch + recent_results + news
        #   FIGHTER_SIGNED    → promotion_status + news
        #   FIGHTER_RETIRED   → champions + news
        #   TITLE_CHANGED     → champions + promotion_status + news
        #   INJURY_RECOVERED  → news (clearance news item written)
        #   CONTRACT_EXPIRED  → promotion_status + news
        #   EVENT_COMPLETED   → recent_results + news
        #
        # The subscribers are LAZY-LOOKUP — they call self.game_state.
        # get_screen("dashboard") on every event so they keep working
        # even if the Dashboard instance is re-created (e.g., a future
        # "reset dashboard" feature). The lookup is O(1) (dict access).
        # ============================================================
        try:
            from event_bus import get_bus, Events
            _bus = get_bus()

            def _mark_dashboard_dirty(*section_names):
                """Helper — look up the dashboard + mark sections dirty.

                Looks up the Dashboard screen via game_state.get_screen
                (lazy lookup — survives Dashboard re-creation). Silently
                no-ops if the Dashboard isn't registered yet (defensive
                against events that fire during app startup before the
                Dashboard is built).
                """
                try:
                    dash = self.game_state.get_screen("dashboard")
                    if dash is None or not hasattr(dash, "mark_section_dirty"):
                        return
                    for sname in section_names:
                        try:
                            dash.mark_section_dirty(sname)
                        except Exception:
                            pass  # defensive — single bad name shouldn't crash
                except Exception as e:
                    print(f"Warning: _mark_dashboard_dirty failed: {e}",
                          flush=True)

            def _on_fight_resolved_dirty(conn, event):
                _mark_dashboard_dirty("fighter_watch", "recent_results", "news")

            def _on_fighter_signed_dirty(conn, event):
                _mark_dashboard_dirty("promotion_status", "news")

            def _on_fighter_retired_dirty(conn, event):
                _mark_dashboard_dirty("champions", "news")

            def _on_title_changed_dirty(conn, event):
                _mark_dashboard_dirty("champions", "promotion_status", "news")

            def _on_injury_recovered_dirty(conn, event):
                _mark_dashboard_dirty("news")

            def _on_contract_expired_dirty(conn, event):
                _mark_dashboard_dirty("promotion_status", "news")

            def _on_event_completed_dirty(conn, event):
                _mark_dashboard_dirty("recent_results", "news")

            _bus.subscribe(Events.FIGHT_RESOLVED, _on_fight_resolved_dirty,
                          name="dashboard_dirty.fight_resolved")
            _bus.subscribe(Events.FIGHTER_SIGNED, _on_fighter_signed_dirty,
                          name="dashboard_dirty.fighter_signed")
            _bus.subscribe(Events.FIGHTER_RETIRED, _on_fighter_retired_dirty,
                          name="dashboard_dirty.fighter_retired")
            _bus.subscribe(Events.TITLE_CHANGED, _on_title_changed_dirty,
                          name="dashboard_dirty.title_changed")
            _bus.subscribe(Events.INJURY_RECOVERED, _on_injury_recovered_dirty,
                          name="dashboard_dirty.injury_recovered")
            _bus.subscribe(Events.CONTRACT_EXPIRED, _on_contract_expired_dirty,
                          name="dashboard_dirty.contract_expired")
            _bus.subscribe(Events.EVENT_COMPLETED, _on_event_completed_dirty,
                          name="dashboard_dirty.event_completed")
        except ImportError:
            pass  # event_bus not available — Dashboard stays dirty-flag-less
        except Exception as e:
            print(f"Warning: dashboard dirty-flag subscribers failed: {e}",
                  flush=True)

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
        from ui.screens.promotion_select import PromotionSelectScreen

        # Unpack the shell components so the promo select screen
        # can take the full window. Note: the sidebar is now wrapped
        # in sidebar_wrapper (per UI-POLISH Fix 6 — the 2px separator),
        # so we unpack the WRAPPER, not the sidebar itself.
        # P2-2: also unpack the top_bar_accent line (created in
        # _build_top_bar) so the promo-select screen takes the full
        # window without a stray crimson line at the top.
        self.top_bar.pack_forget()
        if hasattr(self, "top_bar_accent") and self.top_bar_accent is not None:
            self.top_bar_accent.pack_forget()
        self.sidebar_wrapper.pack_forget()
        self.bottom_bar.pack_forget()
        self.main_content.pack_forget()

        # Create a fresh full-screen container for the promo select
        self.promo_select_screen = PromotionSelectScreen(
            self,
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
        self.promo_select_screen.destroy()

        # Unpack EVERYTHING, then re-pack in the correct order.
        # tkinter pack order is critical: top first, bottom second,
        # then left sidebar (wrapper), then main content fills the rest.
        # Per UI-POLISH Fix 6: sidebar is now inside sidebar_wrapper
        # (2px separator on the right edge), so we pack the wrapper
        # instead of the sidebar directly.
        # P2-2: the top_bar_accent line is re-packed immediately after
        # the top bar so the 2px crimson accent stays between the
        # chrome and the content area.
        self.top_bar.pack_forget()
        if hasattr(self, "top_bar_accent") and self.top_bar_accent is not None:
            self.top_bar_accent.pack_forget()
        self.sidebar_wrapper.pack_forget()
        self.bottom_bar.pack_forget()
        self.main_content.pack_forget()
        self.screen_container.pack_forget()

        # Re-pack in correct order
        self.top_bar.pack(side="top", fill="x")
        if hasattr(self, "top_bar_accent") and self.top_bar_accent is not None:
            self.top_bar_accent.pack(side="top", fill="x")
        self.bottom_bar.pack(side="bottom", fill="x")
        self.sidebar_wrapper.pack(side="left", fill="y")
        self.main_content.pack(side="left", fill="both", expand=True)
        self.screen_container.pack(fill="both", expand=True, padx=20, pady=20)

        # Navigate to the dashboard
        self._navigate("dashboard")
        self._update_top_bar()
        self._update_sidebar()
        self._update_bottom_bar()

    # ============================================================
    # TOP BAR
    # ============================================================

    def _build_top_bar(self):
        """Build the 60px top bar: logo + date + cash + Advance Day.

        Per UI-POLISH Fix 6: the top bar now shows the actual logo
        image (loaded from `src/ui/assets/logo/cage_empire_compact.png`)
        at 40x40px on the far left, instead of the text "CAGE EMPIRE".
        Falls back to the text label if the image can't be loaded
        (PIL missing, file deleted, etc.).

        UI Implementation Plan v3 — P2-2: a 2px crimson accent line is
        packed immediately BELOW the top bar (between it and the main
        content area). This separates the chrome from the workspace —
        the Bloomberg Terminal / ESPN scoreboard aesthetic uses crisp
        accent edges, not floating surfaces. The accent is sparing
        (2px, one brand color) so it stays "calm, data-dense,
        institutional" per the design docs.
        """
        theme = get_theme()
        self.top_bar = ctk.CTkFrame(self, height=60,
                                     corner_radius=0,
                                     fg_color=theme.colors.bg_surface)
        self.top_bar.pack(side="top", fill="x")
        self.top_bar.pack_propagate(False)

        # ---- 2px crimson accent line under the top bar (P2-2) ----
        # Packed immediately after the top_bar (side="top") so Tk's
        # packer places it just below the 60px top bar, before the
        # sidebar/main content area claims the remaining space.
        # Tracked as self.top_bar_accent so _on_promotion_selected's
        # re-pack loop can include it (otherwise the promo-select →
        # dashboard transition would drop the accent line).
        self.top_bar_accent = ctk.CTkFrame(
            self, height=2, corner_radius=0,
            fg_color=theme.colors.crimson,
        )
        self.top_bar_accent.pack(side="top", fill="x")

        # ---- LOGO (image, with text fallback) ----
        # The compact logo is a square mark — 40x40 reads well at the
        # 60px top bar height (10px padding above + below). The text
        # fallback uses the gold H2 font so the brand still reads
        # even if the image is missing.
        self.logo_image = None  # keep a reference so GC doesn't drop it
        logo_loaded = False
        if HAS_PIL and LOGO_COMPACT.exists():
            try:
                img = Image.open(str(LOGO_COMPACT))
                img = img.resize((40, 40), Image.LANCZOS)
                self.logo_image = ctk.CTkImage(
                    light_image=img, dark_image=img, size=(40, 40))
                self.logo_label = ctk.CTkLabel(
                    self.top_bar, image=self.logo_image, text="",
                    anchor="w",
                )
                self.logo_label.pack(side="left", padx=(16, 8))
                logo_loaded = True
            except Exception as e:
                print(f"Warning: logo image load failed: {e}",
                      flush=True)

        if not logo_loaded:
            # Text fallback — gold wordmark, matches the brand.
            # QW5: switched from h2 (Inter 20px Bold) to display_small
            # (Oswald 24px Bold) for the "stadium scoreboard" feel per
            # UI_REDESIGN_VISUAL_PLAN §3.3.
            self.logo_label = ctk.CTkLabel(
                self.top_bar, text="CAGE EMPIRE",
                font=theme.fonts.display_small,
                text_color=theme.colors.gold,
                anchor="w",
            )
            self.logo_label.pack(side="left", padx=20)

        # ---- BRAND WORDMARK (next to logo) ----
        # Even with the logo image, show the wordmark — the logo is a
        # mark, the wordmark is the name. Both reinforce the brand.
        # Hidden if the logo image failed (the text fallback above
        # already shows "CAGE EMPIRE").
        # QW5: switched from h2 (Inter 20px Bold) to display_small
        # (Oswald 24px Bold) for the "stadium scoreboard" feel.
        if logo_loaded:
            self.wordmark_label = ctk.CTkLabel(
                self.top_bar, text="CAGE EMPIRE",
                font=theme.fonts.display_small,
                text_color=theme.colors.gold,
                anchor="w",
            )
            self.wordmark_label.pack(side="left", padx=(0, 16))

        # Sim date (center-left)
        self.date_label = ctk.CTkLabel(self.top_bar, text="",
                                        font=theme.fonts.body,
                                        text_color=theme.colors.text_secondary)
        self.date_label.pack(side="left", padx=20)

        # Cash (center-right)
        self.cash_label = ctk.CTkLabel(self.top_bar, text="",
                                        font=theme.fonts.mono,
                                        text_color=theme.colors.gold)
        self.cash_label.pack(side="right", padx=20)

        # ---- ADVANCE DAY BUTTON (the dopamine button) ----
        # Per UI-POLISH Fix 6: more prominent — larger (180x44),
        # bold H3 font, gold background with a subtle crimson hover.
        # The ▶ glyph + "Advance Day" text + larger size make this
        # the visual focal point of the top bar — the player's eye
        # should land here first.
        self.advance_button = ctk.CTkButton(self.top_bar,
                                             text="▶  Advance Day",
                                             font=theme.fonts.h3,
                                             width=180, height=44,
                                             corner_radius=10,
                                             fg_color=theme.colors.gold,
                                             hover_color=theme.colors.crimson,
                                             text_color=theme.colors.bg_base,
                                             command=self._on_advance_day)
        self.advance_button.pack(side="right", padx=20)

        self._update_top_bar()

    def _update_top_bar(self):
        """Refresh the date + cash display from the DB.

        UI Fix Plan 2 — Phase 1, Fix 3 (AD-6): the date display now
        uses "Month Year" (e.g., "July 2026") instead of "Week N,
        Year N". The week number was cosmetic anyway (no logic reads
        it) + "July 2026" reads as a real-world date the player can
        anchor on, while "Week 3, Year 1" reads as an abstract sim
        counter.

        D-P1-A: the task brief said "current_month at index 4" in
        the get_clock() return tuple, but the SQL in services/clock.
        py:42 is `SELECT current_date, current_day, current_week,
        current_month, current_year, tick_counter` — so the indices
        are 0=date, 1=day, 2=week, 3=month, 4=year, 5=tick. The
        existing code used clock[3] for "week" (actually month) +
        clock[5] for "year" (actually tick_counter) — a pre-existing
        bug that produced output like "Week 7, Year 145" (where 7
        was the month + 145 was the tick counter). Fixed here to use
        clock[3]=month + clock[4]=year so the new "Month Year"
        display shows correct values.
        """
        try:
            clock = get_clock(self.conn)
            if clock:
                date_str = clock[0]  # current_date
                month = clock[3]     # current_month (D-P1-A)
                year = clock[4]      # current_year (D-P1-A)
                # calendar.month_name[0] == '' so guard against
                # out-of-range / None month values defensively.
                month_name = (
                    calendar.month_name[month]
                    if isinstance(month, int) and 1 <= month <= 12
                    else ""
                )
                if year == 0:
                    year = 1
                # Format: "2026-07-20  ·  July 2026"
                # The date_str is the sim's ISO date (already
                # formatted by services.clock); the suffix is the
                # human-readable month + year for quick scanning.
                if month_name:
                    self.date_label.configure(
                        text=f"{date_str}  ·  {month_name} {year}"
                    )
                else:
                    # Defensive fallback if month is invalid — show
                    # just the year (still useful) instead of crashing.
                    self.date_label.configure(
                        text=f"{date_str}  ·  {year}"
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
        """Build the 220px sidebar with nav groups.

        Per UI-POLISH Fix 6: a subtle border on the right edge of the
        sidebar separates it from the main content (previously the
        sidebar + main content had no visual divider — they read as
        one undifferentiated surface).
        Per UI-POLISH Fix 7: the sidebar is wrapped in a
        CTkScrollableFrame so it scrolls if the nav list overflows
        (the existing code already used CTkScrollableFrame here, but
        we verify the scrollbar is themed to match).
        """
        theme = get_theme()
        # Use a 2px right border via a parent frame trick: CTkFrame
        # doesn't natively support per-edge borders, so we wrap the
        # sidebar in a thin container with bg = bg_border to simulate
        # a right-edge separator.
        self.sidebar_wrapper = ctk.CTkFrame(
            self, width=222, corner_radius=0,
            fg_color=theme.colors.bg_border,  # the 2px separator color
        )
        self.sidebar_wrapper.pack(side="left", fill="y")
        self.sidebar_wrapper.pack_propagate(False)

        self.sidebar = ctk.CTkFrame(
            self.sidebar_wrapper, width=220, corner_radius=0,
            fg_color=theme.colors.bg_surface,
        )
        self.sidebar.pack(side="left", fill="both", expand=True)
        self.sidebar.pack_propagate(False)

        # Scrollable sidebar in case nav is too long (D — already
        # present in the original code; preserved here).
        sidebar_scroll = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            scrollbar_button_color=theme.colors.bg_border,
        )
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
        """Build the scrollable main content area.

        UI-REDESIGN-DASH-V2 Fix #3 + #4: apply the noise_grain texture
        to the main window background (subtle grain — "this is a real
        surface, not a flat fill") + place the cage watermark in the
        bottom-right corner (branded paper feel).
        """
        theme = get_theme()
        self.main_content = ctk.CTkFrame(self, corner_radius=0,
                                          fg_color=theme.colors.bg_base)
        self.main_content.pack(side="left", fill="both", expand=True)

        # Fix #3: noise_grain texture overlay on the main window bg.
        # The texture is a 256×256 tile at 3% opacity, tiled across a
        # 1920×1080 canvas via PIL. We place it at the BOTTOM of the
        # pack order (relwidth/relheight=1) so all other widgets render
        # on top of it.
        try:
            from ui.theme import get_noise_grain_texture
            noise_img = get_noise_grain_texture(size=(1920, 1080))
            if noise_img is not None:
                self._bg_texture_label = ctk.CTkLabel(
                    self.main_content, image=noise_img, text="",
                    fg_color="transparent",
                )
                self._bg_texture_label.place(x=0, y=0,
                                              relwidth=1.0, relheight=1.0)
        except Exception as e:
            print(f"Warning: noise_grain texture application failed: {e}",
                  flush=True)

        # Fix #4: cage watermark in the bottom-right corner (5% opacity
        # CE monogram inside an octagon — branded paper feel).
        try:
            from ui.theme import get_cage_watermark
            watermark = get_cage_watermark()
            if watermark is not None:
                self._watermark_label = ctk.CTkLabel(
                    self.main_content, image=watermark, text="",
                    fg_color="transparent",
                )
                self._watermark_label.place(relx=1.0, rely=1.0,
                                             anchor="se", x=-20, y=-20)
        except Exception as e:
            print(f"Warning: cage watermark failed: {e}", flush=True)

        # Screen container — screens pack into this (on TOP of the texture)
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

        RE-ENTRY GUARD: _navigate is called from TWO places:
        1. Directly from button clicks (sidebar, promotion select, hyperlinks)
        2. From state.set_active_screen via the _navigate_callback

        Without a guard, this creates infinite recursion:
        _navigate → set_active_screen → _navigate_callback → _navigate → ...
        The _navigating flag breaks the cycle: when _navigate calls
        set_active_screen, the re-entered _navigate sees the flag + returns
        immediately. The refresh still happens (set_active_screen calls
        self.refresh(name) after the navigate callback).

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
        # RE-ENTRY GUARD: if _navigate is called from set_active_screen's
        # _navigate_callback (i.e., we're already mid-navigation), return
        # immediately. The screen is already packed + the refresh will be
        # called by set_active_screen after this callback returns. Without
        # this guard, _navigate → set_active_screen → _navigate_callback →
        # _navigate creates infinite recursion that crashes with
        # RecursionError on Python 3.14.
        if getattr(self, '_navigating', False):
            return

        self._navigating = True
        try:
            self._do_navigate(screen_name)
        finally:
            self._navigating = False

    def _do_navigate(self, screen_name):
        """Actual navigation logic. Called by _navigate with the re-entry
        guard set. Do NOT call this directly — always go through _navigate.
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
            # Show placeholder with screen name.
            # UI Fix Plan 2 — Phase 3, Fix 2: look up the display name
            # from NAV_GROUPS so the placeholder matches the sidebar
            # label (e.g., "schedule" → "Calendar", not "Schedule").
            display_name = self._lookup_nav_display_name(screen_name) \
                or screen_name.replace('_', ' ').title()
            label = ctk.CTkLabel(self.screen_container,
                                 text=f"[ {display_name} ]\n\n"
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
        # THEME-FONT-FIX: wrap in try/except so we can see what crashes.
        # NOTE: do NOT use traceback.print_exc() here — if the exception
        # is a RecursionError, printing the traceback itself recurses.
        # Just print the exception type + message.
        try:
            self.game_state.set_active_screen(screen_name)
        except ValueError:
            # Screen not registered (placeholder). Update active
            # screen name directly so the sidebar highlight works.
            self.game_state._active_screen = screen_name
        except Exception as e:
            print(f"[app.py] CRASH in _navigate('{screen_name}'): "
                  f"{type(e).__name__}: {e}", flush=True)
            # Show an error message in the content area so the user
            # sees something instead of a frozen screen.
            try:
                err_label = ctk.CTkLabel(
                    self.screen_container,
                    text=f"[Error loading {screen_name}]\n\n"
                         f"{type(e).__name__}: {e}",
                    font=theme.fonts.body,
                    text_color=theme.colors.crimson,
                    justify="left", wraplength=600,
                )
                err_label.pack(expand=True)
            except Exception:
                pass  # If even the error label fails, just log it.
        self._update_sidebar()
        self._update_top_bar()

    # ============================================================
    # UI Fix Plan 2 — Phase 3, Fix 2: NAV display-name lookup helper.
    # ============================================================
    def _lookup_nav_display_name(self, screen_name):
        """Return the player-visible display name for a screen_name.

        Walks NAV_GROUPS looking for the (screen_name, display_name,
        icon) tuple whose first element matches. Returns None if the
        screen_name isn't in any nav group (e.g., "fighter_profile"
        which was hidden per Fix 18 — callers should fall back to
        title-casing the screen_name in that case).
        """
        try:
            for _group_name, screens in NAV_GROUPS:
                for sname, display_name, _icon in screens:
                    if sname == screen_name:
                        return display_name
        except Exception:
            pass
        return None

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
        """Refresh the news ticker from the DB.

        Per UI-POLISH Fix 7: truncate the ticker text to 140 chars
        (was 120) with "..." so longer headlines still fit. The
        bottom bar is 32px tall — at the caption font size (13px),
        ~140 chars fit comfortably in a 1400px-wide window.
        """
        try:
            from services.news_svc import get_latest_news_summary
            summary = get_latest_news_summary(self.conn, limit=3)
            if summary:
                text = "  ·  ".join(summary)
                # Truncate to 140 chars with ellipsis. The brief said
                # "ensure the news ticker text doesn't overflow" —
                # 140 chars is the practical max at the caption font
                # size in a 1400px window.
                if len(text) > 140:
                    text = text[:137] + "..."
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

        Phase 4 — Performance: clears the query cache + portrait
        cache before refreshing so the post-Advance-Day refresh
        recomputes everything from scratch. Without this, the
        Dashboard would show yesterday's hottest-streak fighter
        until the next navigation forced a re-query. The portrait
        cache is also cleared because retirements / new signings
        may invalidate a fighter's portrait path (the cache stores
        CTkImage by fighter_id, so even if the fighter's data
        changed, the cached image is still correct — but clearing
        on Advance Day is the safer default; the cost is one
        re-render per cached portrait on next view).

        TICK-REENGINEER (Fix 2, PERF_ARCH_AUDIT §4.1): mark the
        Advance-Day-affected Dashboard sections dirty BEFORE
        refresh_all so the post-Advance-Day refresh actually rebuilds
        them. Without this, the per-section dirty-flag short-circuit
        would skip sections whose data DID change (headlines, news,
        etc.). Uses mark_advance_day_sections_dirty (7 of 9 sections)
        rather than mark_all_sections_dirty (9 of 9) — champions +
        recent_results don't change on Advance Day (they only change
        on TITLE_CHANGED / FIGHTER_RETIRED / EVENT_COMPLETED, which
        fire their own subscribers). Saves ~107 ms of widget work.
        """
        try:
            advance_day(self.conn)
            self.conn.commit()
            # TICK-REENGEER (Fix 2): mark the Advance-Day-affected
            # Dashboard sections dirty so refresh_all rebuilds them.
            # The tick may have changed daily_headlines,
            # fighter_descriptors, news_items, etc. — 7 of 9 sections
            # need a fresh render. Champions + recent_results are
            # skipped (they only change on discrete events whose
            # subscribers already mark them dirty).
            try:
                if hasattr(self, "dashboard_screen") \
                        and self.dashboard_screen is not None:
                    self.dashboard_screen.mark_advance_day_sections_dirty()
            except Exception as e:
                print(f"Warning: dashboard.mark_advance_day_sections_dirty "
                      f"failed: {e}", flush=True)
            # Phase 4 — clear caches so the refresh shows fresh data.
            try:
                from ui.perf import clear_query_cache, clear_portrait_cache
                clear_query_cache()       # Dashboard hot-query cache
                clear_portrait_cache()     # Fighter Profile portraits
            except Exception as e:
                print(f"Warning: cache clear failed: {e}", flush=True)
            # Lazy refresh: refreshes only the active screen + Dashboard.
            # Other screens refresh on next navigation.
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
