"""Smoke test for Phase 4 performance utilities.

Verifies:
  1. debounce() delays calls + uses the latest args.
  2. portrait cache stores + retrieves CTkImages.
  3. query_cache stores + retrieves values, clear works.
  4. GameState.refresh_all lazy mode skips invisible screens.
  5. GameState.refresh_all force=True refreshes every screen.
  6. clear_query_cache + clear_portrait_cache work.

Run:
    cd /home/z/my-project/cage_empire
    DISPLAY=:99 python3 -m scripts.perf.test_perf
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
ROOT = ctk.CTk()
ROOT.withdraw()


def test_debounce():
    """debounce delays calls + uses the latest args."""
    from ui.perf import debounce

    calls = []

    @debounce(50)
    def fn(self, x):
        calls.append(x)

    # Schedule 3 calls in quick succession.
    fn(ROOT, 1)
    fn(ROOT, 2)
    fn(ROOT, 3)

    # Wait long enough for the debounce to fire.
    ROOT.after(100, ROOT.quit)
    ROOT.mainloop()

    assert calls == [3], f"expected [3], got {calls}"
    print("[PASS] debounce delays + uses latest args")


def test_portrait_cache():
    """portrait cache stores + retrieves."""
    from ui.perf import (
        get_cached_portrait, cache_portrait,
        clear_portrait_cache, portrait_cache_size,
    )
    clear_portrait_cache()

    # Cache miss returns None.
    assert get_cached_portrait(42) is None
    assert portrait_cache_size() == 0

    # Store + retrieve.
    sentinel = object()
    cache_portrait(42, sentinel)
    assert portrait_cache_size() == 1
    assert get_cached_portrait(42) is sentinel

    # LRU touch doesn't change size.
    get_cached_portrait(42)
    assert portrait_cache_size() == 1

    # Different fighter_id is a separate entry.
    sentinel2 = object()
    cache_portrait(99, sentinel2)
    assert portrait_cache_size() == 2
    assert get_cached_portrait(99) is sentinel2

    # Clear empties the cache.
    clear_portrait_cache()
    assert portrait_cache_size() == 0
    assert get_cached_portrait(42) is None
    print("[PASS] portrait cache stores + retrieves + clears")


def test_portrait_cache_lru_eviction():
    """LRU eviction drops oldest entries past the max."""
    from ui import perf
    perf.clear_portrait_cache()
    # Temporarily lower the max for the test.
    original_max = perf._PORTRAIT_CACHE_MAX
    perf._PORTRAIT_CACHE_MAX = 3
    try:
        perf.cache_portrait(1, "a")
        perf.cache_portrait(2, "b")
        perf.cache_portrait(3, "c")
        assert perf.portrait_cache_size() == 3

        # Adding a 4th should evict fighter 1 (oldest).
        perf.cache_portrait(4, "d")
        assert perf.portrait_cache_size() == 3
        assert perf.get_cached_portrait(1) is None
        assert perf.get_cached_portrait(4) == "d"

        # Touch fighter 2 (now the LRU).
        perf.get_cached_portrait(2)
        # Add a 5th — should evict fighter 3 (now the LRU).
        perf.cache_portrait(5, "e")
        assert perf.portrait_cache_size() == 3
        assert perf.get_cached_portrait(3) is None
        assert perf.get_cached_portrait(2) == "b"
    finally:
        perf._PORTRAIT_CACHE_MAX = original_max
        perf.clear_portrait_cache()
    print("[PASS] portrait cache LRU eviction works")


def test_query_cache():
    """query_cache stores + retrieves + clears."""
    from ui.perf import query_cached, query_get, query_set, clear_query_cache

    clear_query_cache()

    # Cache miss calls the builder.
    builds = []
    def builder():
        builds.append(1)
        return "value"
    v = query_cached("ns1", "k1", builder)
    assert v == "value"
    assert len(builds) == 1

    # Cache hit doesn't call the builder.
    v = query_cached("ns1", "k1", builder)
    assert v == "value"
    assert len(builds) == 1

    # Different key is a miss.
    v = query_cached("ns1", "k2", builder)
    assert len(builds) == 2

    # Different namespace is a miss.
    v = query_cached("ns2", "k1", builder)
    assert len(builds) == 3

    # Direct get/set.
    query_set("ns1", "k3", "direct")
    assert query_get("ns1", "k3") == "direct"
    assert query_get("ns1", "missing", default="def") == "def"

    # Clear one namespace.
    clear_query_cache("ns1")
    assert query_get("ns1", "k1") is None
    assert query_get("ns2", "k1") == "value"  # ns2 still cached

    # Clear all.
    clear_query_cache()
    assert query_get("ns2", "k1") is None
    print("[PASS] query_cache stores + retrieves + clears (per-ns + all)")


def test_lazy_refresh_skips_invisible_screens():
    """GameState.refresh_all (lazy) only refreshes active + dashboard."""
    import sqlite3
    from ui.state import GameState

    # Build a throwaway DB (in-memory).
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE simulation_clock (clock_id INTEGER PRIMARY KEY, current_date TEXT, current_day INTEGER, current_week INTEGER, current_month INTEGER, current_year INTEGER)")
    conn.execute("INSERT INTO simulation_clock VALUES (1, '2026-07-20', 1, 1, 7, 2026)")
    conn.commit()

    # Reset the singleton.
    GameState._instance = None
    state = GameState(conn, player_promotion_id=1)

    # Register 3 fake screens with refresh counters.
    refresh_counts = {"dashboard": 0, "roster": 0, "free_agents": 0}

    def make_cb(name):
        def cb():
            refresh_counts[name] += 1
        return cb

    state.register_screen("dashboard", object(), make_cb("dashboard"))
    state.register_screen("roster", object(), make_cb("roster"))
    state.register_screen("free_agents", object(), make_cb("free_agents"))

    # Active = roster. refresh_all (lazy) should refresh roster + dashboard.
    state._active_screen = "roster"
    state.refresh_all()
    assert refresh_counts == {"dashboard": 1, "roster": 1, "free_agents": 0}, \
        f"lazy refresh counts wrong: {refresh_counts}"

    # Active = dashboard. refresh_all (lazy) should refresh ONLY dashboard.
    state._active_screen = "dashboard"
    state.refresh_all()
    assert refresh_counts == {"dashboard": 2, "roster": 1, "free_agents": 0}, \
        f"lazy refresh counts wrong: {refresh_counts}"

    # force=True refreshes every screen.
    state.refresh_all(force=True)
    assert refresh_counts == {"dashboard": 3, "roster": 2, "free_agents": 1}, \
        f"force refresh counts wrong: {refresh_counts}"

    print("[PASS] refresh_all lazy skips invisible screens, force refreshes all")


def main():
    print("CAGE EMPIRE — Phase 4 Performance Utilities Smoke Test")
    print()
    test_debounce()
    test_portrait_cache()
    test_portrait_cache_lru_eviction()
    test_query_cache()
    test_lazy_refresh_skips_invisible_screens()
    print()
    print("All Phase 4 perf smoke tests PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
