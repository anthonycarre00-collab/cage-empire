"""CAGE EMPIRE — GameState singleton (Stage 6 — Task 6.2).

The game-state layer that manages the sqlite3.Connection, the
current screen, the current theme (Office/Fight Night), and
screen refresh callbacks.

Per docs/TASK_6_0_PLAN.md §2.4:
  - refresh_all() on user-initiated actions (Advance Day, Resolve
    Fight, Save/Load, theme toggle)
  - refresh(name) on screen navigation (only refresh the newly-
    active screen)
  - Screens that are not visible skip refresh (they'll refresh
    when next shown)

CONVENTIONS compliance:
  §13 — Design Law: infrastructure supporting every pillar.
  §14 — Voice Layer: the GameState itself doesn't display text,
        but it manages the theme that shapes how text is rendered.
  §15 — Event Bus: GameState is NOT event-bus-driven. It's a UI-
        layer concern, triggered by user navigation + user actions.

Usage:
  from ui.state import GameState

  state = GameState(conn)  # created once at app startup
  state.register_screen("dashboard", dashboard_instance,
                         dashboard_instance.refresh)
  state.set_active_screen("dashboard")  # navigate
  state.refresh_all()  # after Advance Day / Resolve Fight
  state.set_theme("fight_night")  # switch to Fight Night Mode
"""

import sqlite3
from pathlib import Path

from ui.theme import set_theme, get_theme, on_theme_change


class GameState:
    """Singleton game-state layer.

    Holds:
      - conn: the sqlite3.Connection to data/cage_empire.db
      - player_promotion_id: which promotion the player controls
        (hardcoded to 1 until Task 6.15 adds the player entity)
      - screens: dict of name -> (instance, refresh_callback)
      - active_screen: the name of the currently-visible screen
      - theme: "office" or "fight_night"

    Every screen registers a refresh_callback. When the state
    changes (tick advanced, fight resolved, fighter signed),
    GameState calls refresh_callback on every registered screen.
    Screens that are not visible skip the refresh.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern — only one GameState instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, conn=None, player_promotion_id=None):
        """Initialize the GameState.

        Args:
            conn: sqlite3.Connection to the world DB. Required on
                  first init; ignored on subsequent calls (singleton).
            player_promotion_id: which promotion the player controls.
                  None until the player picks one on the startup screen.
        """
        if self._initialized:
            return
        self._initialized = True

        self.conn = conn
        self.player_promotion_id = player_promotion_id
        self._screens = {}  # name -> (instance, refresh_callback)
        self._active_screen = None
        self._theme = "office"

        # UI Fix Plan 2 — Phase 1, Fix 14: navigation back-stack.
        # Tracks the screen names the player visited BEFORE the current
        # one so the Fighter Profile's Back button can return the
        # player to wherever they came from (Roster, Free Agents,
        # Dashboard, etc.) instead of hard-coding "roster". Cap at 10
        # entries to bound memory + prevent infinite loops.
        # See AD-2 in docs/UI_FIX_PLAN_2.md.
        self._nav_stack = []

        # Register for theme change callbacks from ui.theme
        on_theme_change(self._on_theme_changed)

    def _on_theme_changed(self, new_theme):
        """Called when ui.theme.set_theme() fires.

        Updates internal state + triggers refresh_all so every
        screen re-renders with the new theme's colors/fonts.
        """
        self._theme = new_theme.name
        self.refresh_all()

    # ============================================================
    # SCREEN REGISTRATION + NAVIGATION
    # ============================================================

    def register_screen(self, name, instance, refresh_callback=None):
        """Register a screen with the GameState.

        Args:
            name: unique screen name (e.g., "dashboard", "roster")
            instance: the screen widget instance
            refresh_callback: callable that re-queries data + re-renders.
                              Called with no arguments. May be None if
                              the screen has no dynamic data.
        """
        self._screens[name] = (instance, refresh_callback)

    def unregister_screen(self, name):
        """Remove a screen from the GameState."""
        if name in self._screens:
            del self._screens[name]
        if self._active_screen == name:
            self._active_screen = None

    def set_active_screen(self, name):
        """Navigate to a screen.

        Refreshes the now-active screen (it might have stale data
        from the last time it was visible).

        UI Fix Plan 2 — Phase 1, Fix 14 (AD-2): before flipping the
        active screen, push the OLD active screen onto `_nav_stack`
        so `go_back()` can later return the player to where they
        came from. Skipped when:
          - there is no old active screen (first navigation)
          - the new screen is the SAME as the old (re-nav to current)
        The stack is capped at 10 entries (oldest dropped first) so
        memory stays bounded + the back history can't grow without
        limit on long sessions.
        """
        if name not in self._screens:
            raise ValueError(f"Screen '{name}' not registered")
        # Push the OLD active screen (if any + if different) so the
        # Fighter Profile's Back button can return the player to
        # wherever they navigated FROM (Roster, Free Agents,
        # Dashboard, etc.). See AD-2 in docs/UI_FIX_PLAN_2.md.
        if (self._active_screen is not None
                and self._active_screen != name):
            self._nav_stack.append(self._active_screen)
            # Cap at 10 — drop the OLDEST entry (FIFO overflow).
            if len(self._nav_stack) > 10:
                self._nav_stack.pop(0)
        self._active_screen = name
        self.refresh(name)

    def go_back(self):
        """Pop the navigation back-stack + navigate to the popped screen.

        UI Fix Plan 2 — Phase 1, Fix 14 (AD-2). Returns the player to
        the screen they were on BEFORE the current one. Used by the
        Fighter Profile's Back button so it works no matter where the
        player came from (Roster, Free Agents, Dashboard, etc.) instead
        of always returning to the Roster.

        Returns:
            The screen name navigated to, or None if the back-stack
            was empty (caller is expected to fall back to a sensible
            default — typically "roster").
        """
        if not self._nav_stack:
            return None
        prev = self._nav_stack.pop()
        # set_active_screen would push the CURRENT screen back onto
        # the stack — but we just popped, so we want a one-way back
        # navigation, not a push. Set _active_screen directly + refresh
        # so the screen re-queries + re-renders, but don't re-push.
        if prev not in self._screens:
            # Defensive: if the previous screen was unregistered
            # between pushes (e.g., a screen torn down at runtime),
            # we can't navigate back to it. Return None so the caller
            # falls back to its default.
            return None
        self._active_screen = prev
        self.refresh(prev)
        return prev

    def can_go_back(self):
        """Return True if the back-stack has at least one entry.

        UI Fix Plan 2 — Phase 1, Fix 14 (AD-2). Used by widgets that
        want to enable/disable a Back button based on whether there's
        anywhere to go back to.
        """
        return len(self._nav_stack) > 0

    def get_active_screen(self):
        """Return the name of the currently-active screen."""
        return self._active_screen

    def get_screen(self, name):
        """Return the instance of a registered screen."""
        entry = self._screens.get(name)
        return entry[0] if entry else None

    # ============================================================
    # REFRESH
    # ============================================================

    def refresh(self, name=None):
        """Refresh one screen (by name) or the active screen.

        Used when only one screen's data changed (e.g., navigating
        to a new screen — only that screen needs refresh).
        """
        if name is None:
            name = self._active_screen
        if name is None:
            return
        entry = self._screens.get(name)
        if entry and entry[1]:
            try:
                entry[1]()
            except Exception as e:
                print(f"Warning: refresh failed for screen '{name}': {e}",
                      flush=True)

    def refresh_all(self):
        """Refresh ALL registered screens.

        Used after major state changes:
          - Advance Day button (every screen's data may have changed)
          - Resolve Fight button (roster, rankings, news, finance all change)
          - Save / Load (entire DB state replaced)
          - Theme toggle (every screen re-renders with new colors/fonts)
        """
        for name, (instance, cb) in self._screens.items():
            if cb:
                try:
                    cb()
                except Exception as e:
                    print(f"Warning: refresh_all failed for screen '{name}': {e}",
                          flush=True)

    # ============================================================
    # THEME
    # ============================================================

    def set_theme(self, mode):
        """Switch the active theme. Delegates to ui.theme.set_theme().

        Args:
            mode: "office" or "fight_night"
        """
        set_theme(mode)

    def get_theme(self):
        """Return the currently active Theme instance."""
        return get_theme()

    def get_theme_name(self):
        """Return the active theme name ('office' or 'fight_night')."""
        return self._theme

    # ============================================================
    # DB ACCESS
    # ============================================================

    def get_conn(self):
        """Return the sqlite3.Connection."""
        return self.conn

    def get_player_promotion_id(self):
        """Return the promotion_id the player controls."""
        return self.player_promotion_id


# ============================================================
# MODULE-LEVEL ACCESSOR
# ============================================================

def get_state():
    """Return the singleton GameState instance.

    Raises RuntimeError if GameState hasn't been initialized yet
    (call GameState(conn) first at app startup).
    """
    if GameState._instance is None:
        raise RuntimeError("GameState not initialized. Call GameState(conn) first.")
    return GameState._instance
