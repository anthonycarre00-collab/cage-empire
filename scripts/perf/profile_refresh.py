"""Time the full refresh cycle of each screen — what the player
actually experiences on Advance Day + on navigation.

This script imports the screen widgets directly + calls their
_refresh() methods, measuring wall-clock time for each. It does NOT
launch the Tk mainloop — we just need a Tk root to instantiate CTk
widgets (ctk.CTk() with withdraw()).

Usage:
    cd /home/z/my-project/cage_empire
    python -m scripts.perf.profile_refresh
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import customtkinter as ctk

# Initialise a hidden Tk root — required for any CTk widget.
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
ROOT = ctk.CTk()
ROOT.withdraw()  # don't show the window


def _open_ro() -> sqlite3.Connection:
    """Open the world DB read-only."""
    db_path = PROJECT_ROOT / "data" / "cage_empire.db"
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _median_ms(fn, iters=5):
    """Run fn() iters times, return median ms."""
    times = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    times.sort()
    return times[len(times) // 2]


def main():
    from ui.state import GameState
    from ui.screens.dashboard import DashboardScreen
    from ui.screens.roster import RosterScreen
    from ui.screens.free_agents import FreeAgentsScreen
    from ui.screens.fighter_profile import FighterProfileScreen
    from ui.screens.scouting import ScoutingScreen

    print("CAGE EMPIRE — Refresh Profile (full screen refresh cycle)")
    print()

    # Set up the singleton GameState with a read-only conn + the
    # first promotion (Alpha Combat Federation, 60 fighters).
    conn = _open_ro()
    # Reset the singleton between runs.
    GameState._instance = None
    state = GameState(conn, player_promotion_id=1)

    # Helper to instantiate a screen + call _refresh.
    def make_screen(cls, **kwargs):
        screen = cls(ROOT, **kwargs)
        # Many screens use after(50, self._refresh) — call it now.
        try:
            screen._refresh()
        except Exception as e:
            print(f"  (refresh failed: {e})")
        return screen

    # --- Dashboard ---
    print("--- Dashboard ---")
    dash = make_screen(DashboardScreen)
    ms = _median_ms(dash._refresh)
    print(f"  DashboardScreen._refresh: {ms:.1f} ms")

    # --- Roster ---
    print("\n--- Roster ---")
    roster = make_screen(RosterScreen)
    ms = _median_ms(roster._refresh)
    print(f"  RosterScreen._refresh: {ms:.1f} ms")

    # --- Free Agents ---
    print("\n--- Free Agents ---")
    fa = make_screen(FreeAgentsScreen)
    ms = _median_ms(fa._refresh)
    print(f"  FreeAgentsScreen._refresh: {ms:.1f} ms")

    # --- Fighter Profile (fighter 4) ---
    print("\n--- Fighter Profile ---")
    fp = make_screen(FighterProfileScreen)
    fp.set_fighter_id(4)
    # First refresh (cache miss).
    t0 = time.perf_counter()
    fp._refresh()
    t1 = time.perf_counter()
    print(f"  FighterProfileScreen._refresh (cache miss): {(t1-t0)*1000:.1f} ms")
    # Second refresh (cache hit — portrait already loaded).
    t0 = time.perf_counter()
    fp._refresh()
    t1 = time.perf_counter()
    print(f"  FighterProfileScreen._refresh (cache hit):  {(t1-t0)*1000:.1f} ms")

    # --- Scouting ---
    print("\n--- Scouting ---")
    scout = make_screen(ScoutingScreen)
    ms = _median_ms(scout._refresh)
    print(f"  ScoutingScreen._refresh: {ms:.1f} ms")

    # --- refresh_all (simulates Advance Day) ---
    print("\n--- refresh_all (simulates Advance Day, lazy mode) ---")
    # Register all screens with the state.
    state.register_screen("dashboard", dash, dash._refresh)
    state.register_screen("roster", roster, roster._refresh)
    state.register_screen("free_agents", fa, fa._refresh)
    state.register_screen("fighter_profile", fp, fp._refresh)
    state.register_screen("scouting", scout, scout._refresh)

    # Set active screen to dashboard (so lazy refresh hits dashboard).
    state._active_screen = "dashboard"

    ms = _median_ms(state.refresh_all)
    print(f"  refresh_all (lazy, active=dashboard): {ms:.1f} ms")

    # Switch active to roster + refresh_all.
    state._active_screen = "roster"
    ms = _median_ms(state.refresh_all)
    print(f"  refresh_all (lazy, active=roster):    {ms:.1f} ms")

    # Force refresh (full — simulates theme toggle / Load).
    ms = _median_ms(lambda: state.refresh_all(force=True))
    print(f"  refresh_all (force=True):             {ms:.1f} ms")

    print("\n=== Done ===")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
