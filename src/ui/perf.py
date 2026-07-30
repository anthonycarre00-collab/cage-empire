"""CAGE EMPIRE — Performance utilities (Phase 4 — UI Fix Plan 2, Fix 20).

This module provides three drop-in utilities used by the UI layer to
reduce redundant work on the critical path (page load + Advance Day):

  1. `debounce(ms)` — decorator that delays a function call until
     `ms` milliseconds have elapsed without further calls. Used on
     search-entry keystroke handlers so we don't re-query the DB +
     rebuild 120 widgets on every keystroke. The trailing call uses
     CTk's `widget.after(ms, ...)` timer, so it integrates cleanly
     with the Tk event loop (no threads, no asyncio).

  2. `portrait_cache` — module-level LRU cache for loaded CTkImage
     portraits. The Fighter Profile screen re-loads the same PIL
     image every time the player navigates to a profile (or every
     time refresh fires). With the cache, repeated loads of the
     same fighter_id return the cached CTkImage in O(1). The cache
     holds 200 entries (LRU eviction) — covers the typical "browse
     20 fighters in a session" pattern without growing unbounded.

  3. `query_cache` — a simple invalidate-on-Advance-Day cache for
     expensive Dashboard queries (hottest-streak, top-prospect).
     Cached values are returned instantly on subsequent refreshes
     until `clear_query_cache()` is called (which the
     CageEmpireApp._on_advance_day does after the tick completes).

CONVENTIONS compliance:
  §13 — Design Law: infrastructure. No user-visible text.
  §14 — Voice Layer: doesn't display anything.
  §15 — Event Bus: not event-bus-driven. Cleared by the
        Advance Day button handler (UI-layer trigger).
  §17 — UI Snapshot Rule: the cache stores already-decoded voice
        phrases (or the raw "label||phrase" strings), so the §17
        rule is preserved (UI only reads the snapshot, not the
        underlying live attribute tables).

Why a single module: the three utilities are small + cross-referenced
by the screen refresh callbacks. Putting them in one file keeps the
"performance layer" cohesive + makes it easy to find every perf
helper from a single import.
"""

from __future__ import annotations

import functools
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

import customtkinter as ctk


# ============================================================
# 1. DEBOUNCE
# ============================================================

def debounce(ms: int = 200):
    """Decorator: delay calls until `ms` ms have elapsed without
    further calls. The latest arguments are used (trailing-edge).

    Usage:
        @debounce(200)
        def _on_search_change(self, event=None):
            ...

    How it works:
      - Each call cancels any pending timer (stored on the function
        object as `_debounce_timer`).
      - A new timer is scheduled via `widget.after(ms, _fire)` where
        `widget` is auto-detected from the bound `self` (if the
        decorated function is a method, `self` is a CTk widget).
      - When the timer fires, the wrapped function is called with
        the most recent arguments.

    The decorator handles two cases:
      1. Method on a CTk widget — uses `self.after(ms, ...)`.
      2. Standalone function with no `self` — uses the Tk root's
         `after` via `ctk.CTk._default_root`. Defensive — if no
         root exists yet, falls back to immediate call (no debounce).

    Args:
        ms: delay in milliseconds. 200ms is the sweet spot for
            search-as-you-type: feels instant to the user but skips
            4-5 keystrokes of redundant work for a fast typist.

    Returns:
        A wrapper function with the same signature as the decorated
        function. The wrapper has an `_cancel_pending()` method for
        tests / explicit cancellation.
    """
    def decorator(fn: Callable) -> Callable:
        # Per-decoration state — holds the pending after() id + the
        # latest args/kwargs. Stored as a dict so the inner closure
        # can mutate it.
        state: dict[str, Any] = {
            "after_id": None,
            "pending_args": None,
            "pending_kwargs": None,
        }

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Stash the latest call's args.
            state["pending_args"] = args
            state["pending_kwargs"] = kwargs

            # Cancel any previous pending timer.
            after_id = state.get("after_id")
            if after_id is not None:
                try:
                    # Try to cancel via the widget that scheduled it.
                    # The widget is the first arg if fn is a method.
                    widget = args[0] if args else None
                    if widget is not None and hasattr(widget, "after_cancel"):
                        widget.after_cancel(after_id)
                except Exception:
                    pass
                state["after_id"] = None

            # Find a widget to schedule the timer on. Methods on
            # CTk widgets pass `self` as the first positional arg.
            widget = args[0] if args else None
            scheduler = None
            if widget is not None and hasattr(widget, "after"):
                scheduler = widget
            elif ctk.CTk._default_root is not None:
                scheduler = ctk.CTk._default_root

            def _fire():
                state["after_id"] = None
                a = state["pending_args"] or ()
                k = state["pending_kwargs"] or {}
                try:
                    fn(*a, **k)
                except Exception as e:
                    print(f"Warning: debounced fn {fn.__name__} failed: {e}",
                          flush=True)

            if scheduler is not None:
                state["after_id"] = scheduler.after(ms, _fire)
            else:
                # No Tk root yet — call immediately (defensive).
                _fire()

        def _cancel_pending():
            """Cancel any pending debounced call (for tests)."""
            after_id = state.get("after_id")
            if after_id is not None:
                try:
                    widget = state.get("pending_args", (None,))[0] if state.get("pending_args") else None
                    if widget is not None and hasattr(widget, "after_cancel"):
                        widget.after_cancel(after_id)
                except Exception:
                    pass
                state["after_id"] = None

        wrapper._cancel_pending = _cancel_pending
        wrapper._state = state  # for inspection in tests
        return wrapper

    return decorator


# ============================================================
# 2. PORTRAIT CACHE
# ============================================================

# Module-level LRU cache. Stores (fighter_id → CTkImage). When the
# cache fills, the OLDEST entry is evicted (OrderedDict.move_to_end
# on access + popitem(last=False) on overflow). The CTkImage holds a
# reference to the underlying PIL image, so a cached portrait is
# ready to display instantly without re-opening the PNG file or
# re-running the LANCZOS resize.
_PORTRAIT_CACHE: OrderedDict[int, Any] = OrderedDict()
_PORTRAIT_CACHE_MAX = 200


def get_cached_portrait(fighter_id: int) -> Optional[Any]:
    """Return the cached CTkImage for fighter_id, or None.

    The caller is responsible for building the CTkImage if None is
    returned (via _load_portrait_image in fighter_profile.py) and
    then storing it via `cache_portrait(fighter_id, image)`.
    """
    if fighter_id is None:
        return None
    img = _PORTRAIT_CACHE.get(fighter_id)
    if img is not None:
        # LRU touch — move to end so it's the most-recently-used.
        _PORTRAIT_CACHE.move_to_end(fighter_id)
    return img


def cache_portrait(fighter_id: int, image: Any) -> None:
    """Store a CTkImage in the portrait cache.

    Called by the Fighter Profile screen after building the image.
    Defensive — if fighter_id is None or image is None, no-op.
    """
    if fighter_id is None or image is None:
        return
    _PORTRAIT_CACHE[fighter_id] = image
    _PORTRAIT_CACHE.move_to_end(fighter_id)
    # Evict oldest if over capacity.
    while len(_PORTRAIT_CACHE) > _PORTRAIT_CACHE_MAX:
        _PORTRAIT_CACHE.popitem(last=False)


def clear_portrait_cache() -> None:
    """Empty the portrait cache (e.g., on theme change so the gold
    border tint can be re-applied — though the CTkImage itself is
    theme-agnostic, the surrounding frame's border_color is read at
    configure time, so we don't strictly need to clear on theme
    change. Still useful for tests / explicit memory cleanup).
    """
    _PORTRAIT_CACHE.clear()


def portrait_cache_size() -> int:
    """Return the current number of cached portraits (for diagnostics)."""
    return len(_PORTRAIT_CACHE)


# ============================================================
# 3. QUERY CACHE (Dashboard hot queries)
# ============================================================

# Module-level dict-of-dicts. Each "namespace" (e.g., "dashboard")
# holds a dict of cached values. The whole namespace is cleared on
# Advance Day (or any other event that invalidates the cached data).
#
# Why namespaced? Future code may want to cache per-screen (roster
# search results, free agent lists) with different invalidation
# rules. Namespacing keeps the API clean.
_QUERY_CACHES: dict[str, dict[str, Any]] = {}


def query_get(namespace: str, key: str, default=None):
    """Return the cached value for (namespace, key), or default."""
    ns = _QUERY_CACHES.get(namespace)
    if ns is None:
        return default
    return ns.get(key, default)


def query_set(namespace: str, key: str, value: Any) -> None:
    """Store a value in the query cache under (namespace, key)."""
    ns = _QUERY_CACHES.setdefault(namespace, {})
    ns[key] = value


def query_cached(namespace: str, key: str, builder: Callable[[], Any]):
    """Return the cached value for (namespace, key), or call builder()
    to compute + cache it.

    Usage:
        streak_id = query_cached(
            "dashboard", "hottest_streak_fighter_id",
            lambda: self._find_hottest_streak_fighter(conn, exclude_ids),
        )

    The builder is only called on a cache miss. Subsequent calls
    (within the same Advance Day cycle) return the cached value
    instantly without re-running the SQL.
    """
    ns = _QUERY_CACHES.get(namespace)
    if ns is not None and key in ns:
        return ns[key]
    value = builder()
    query_set(namespace, key, value)
    return value


def clear_query_cache(namespace: str = None) -> None:
    """Clear one namespace, or all namespaces if None.

    Called by CageEmpireApp._on_advance_day after advance_day(conn)
    completes — every cached query result is now stale (the tick
    may have changed fighter_descriptors, daily_headlines, news,
    etc.) and must be recomputed on the next refresh.
    """
    if namespace is None:
        _QUERY_CACHES.clear()
    else:
        _QUERY_CACHES.pop(namespace, None)


def query_cache_namespaces() -> list[str]:
    """Return the list of active namespaces (for diagnostics)."""
    return list(_QUERY_CACHES.keys())


# ============================================================
# 4. TIMING DECORATOR (used by profile_screens.py + tests)
# ============================================================

def timed(label: str = None):
    """Decorator: print timing info for each call to the wrapped fn.

    Usage:
        @timed("RosterScreen._refresh")
        def _refresh(self):
            ...

    The label defaults to the function's qualified name. Prints to
    stdout (flush=True) so the timing appears in real time alongside
    any other prints. Disabled if `CAGE_EMPIRE_NO_TIMING` env var is
    set (so tests can opt out).
    """
    import os
    if os.environ.get("CAGE_EMPIRE_NO_TIMING"):
        # No-op decorator — returns fn unchanged.
        def noop_decorator(fn):
            return fn
        return noop_decorator

    def decorator(fn: Callable) -> Callable:
        lbl = label or getattr(fn, "__qualname__", fn.__name__)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                t1 = time.perf_counter()
                ms = (t1 - t0) * 1000.0
                print(f"  [timed] {lbl}: {ms:.1f} ms", flush=True)

        return wrapper

    return decorator
