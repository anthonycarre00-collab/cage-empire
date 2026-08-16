"""CAGE EMPIRE — HyperlinkLabel widget (UI Fix Plan 2 — Phase 1, Fix 5).

A clickable text label that navigates to a fighter's profile when
clicked. Subclasses `CTkLabel` so it inherits all label behaviour
(text, font, anchor, wraplength) and adds:

  - Gold text colour (theme.colors.gold — the brand accent for
    champion / title / hyperlink affordances).
  - Hand cursor on hover (cursor="hand2") — the standard desktop
    idiom for "this is clickable".
  - Hover effect: text lightens from `gold` to `gold_bright` on
    <Enter> + restores on <Leave>. Subtle but legible — the player
    gets feedback that the link is interactive.
  - Click handler: <Button-1> navigates to the Fighter Profile
    screen for `fighter_id` (if set) AND/OR calls `on_click` (if
    provided). Both can be set — the Fighter Profile navigation
    fires first, then the custom callback.

Per AD-1 in docs/UI_FIX_PLAN_2.md: this widget unblocks Phase 3
fixes 7 (champion hyperlinks on the Dashboard) and 13 (Roster
hyperlinks). Until this widget existed, every screen that wanted
to link to a fighter profile had to roll its own button-style
clickable, which was inconsistent + couldn't carry a fighter_id.

CONVENTIONS compliance:
  §14 — Voice Layer: the link TEXT is whatever the caller passes
        (typically a fighter name). Names are NOT raw attribute
        values per §14 — they're identity strings.
  §17 — UI Snapshot Rule: the widget doesn't query the DB itself.
        It just navigates. The Fighter Profile screen (which it
        navigates to) reads from cache tables per §17.

Usage:
  from ui.widgets.hyperlink import HyperlinkLabel

  # Simple — navigates to Fighter Profile for fighter_id=42:
  link = HyperlinkLabel(parent, text="John Vale", fighter_id=42)

  # With custom click handler (in addition to fighter nav):
  link = HyperlinkLabel(
      parent, text="View Details", fighter_id=42,
      on_click=lambda fid: print(f"clicked {fid}"),
  )

  # Standalone callback (no fighter_id — just a clickable label):
  link = HyperlinkLabel(
      parent, text="Sort by Form", on_click=my_sort_handler,
  )
"""

import customtkinter as ctk

from ui.theme import get_theme
from ui.state import get_state


# Hover-color lookup keyed by theme name (P2-4 — UI Implementation
# Plan v3). Phase 1.5 QW6: previously this map held hardcoded hex
# values per theme. Now the entries are FALLBACKS only — the primary
# source of truth is theme.colors.gold_bright (set in OfficeColors /
# FightNightColors per UI_REDESIGN_VISUAL_PLAN §2.2). _hover_gold_for_
# current_theme() reads from the theme first; the map only kicks in
# if the theme lookup fails (defensive — keeps the widget functional
# without crashing on theme lookup).
#
# - Office mode: resting gold #e0a957 → hover #f5c878 (warmer, brighter)
# - Fight Night mode: resting gold #f0c060 → hover #ffd700 (full gold)
#   The Fight Night palette is already brighter/saturated, so the
#   hover pushes into a richer gold rather than a lighter wash.
_HOVER_GOLD_BY_THEME = {
    "office": "#f5c878",
    "fight_night": "#ffd700",
}

# Default fallback if a future theme adds a new name we don't know
# about — keeps the widget functional without crashing on theme lookup.
_HOVER_GOLD_DEFAULT = "#f5c878"


def _hover_gold_for_current_theme():
    """Resolve the hover gold color for the currently active theme.

    P2-4: previously this was a module-level constant hardcoded to
    "#f0c878". Now it's a lookup so the hover color tracks the theme
    (Office vs Fight Night). Phase 1.5 QW6: now reads from
    theme.colors.gold_bright FIRST (the source of truth per the
    redesigned theme system), falling back to the per-theme map only
    if the theme doesn't expose gold_bright (defensive). Called from
    the <Enter> handler on every hover — cheap (cached global + dict
    lookup).

    Returns:
        Hex color string suitable for CTk's text_color configure.
    """
    try:
        theme = get_theme()
        # QW6: prefer theme.colors.gold_bright (the source of truth).
        gold_bright = getattr(theme.colors, "gold_bright", None)
        if gold_bright:
            return gold_bright
        # Fallback: per-theme map (legacy, kept for back-compat with
        # any custom themes that don't expose gold_bright).
        return _HOVER_GOLD_BY_THEME.get(theme.name, _HOVER_GOLD_DEFAULT)
    except Exception:
        # Defensive — if get_theme() somehow fails (e.g. imported
        # before theme system is initialized), fall back to the
        # Office hover shade. The hover effect is cosmetic.
        return _HOVER_GOLD_DEFAULT


class HyperlinkLabel(ctk.CTkLabel):
    """A clickable text label that navigates to a fighter's profile.

    Subclasses `CTkLabel` so all standard label kwargs work (text,
    font, anchor, wraplength, etc.). Adds fighter-id-aware click
    navigation + a gold hover effect.

    Args:
        parent: the parent widget.
        text: the link text (typically a fighter name).
        fighter_id: optional int — if set, clicking navigates to the
            Fighter Profile screen for this fighter (calls
            `fighter_profile_screen.set_fighter_id(fid)` + then
            `state.set_active_screen("fighter_profile")`).
        on_click: optional callable — invoked AFTER the fighter
            navigation (if any). Receives the fighter_id as its
            sole argument (or None if no fighter_id was set).
        **kwargs: passed through to CTkLabel.

    The hover effect binds <Enter> + <Leave> on the underlying Tk
    label. The click binds <Button-1>. These are bound via `bind`
    (not `command`) because CTkLabel doesn't have a command — labels
    aren't normally interactive.
    """

    def __init__(self, parent, text="", fighter_id=None,
                 on_click=None, **kwargs):
        theme = get_theme()

        # Default text colour to theme gold (caller can override
        # via kwargs if they want a different accent). Default font
        # to body — caller can override to body_small for compact
        # contexts (e.g., table rows).
        kwargs.setdefault("text_color", theme.colors.gold)
        kwargs.setdefault("font", theme.fonts.body)

        super().__init__(parent, text=text, **kwargs)

        self._fighter_id = fighter_id
        self._on_click = on_click
        self._rest_color = kwargs["text_color"]  # what to restore to on <Leave>

        # Hand cursor — the standard desktop idiom for "this is
        # clickable". CTkLabel.configure() forwards cursor to the
        # underlying Tk widget.
        try:
            self.configure(cursor="hand2")
        except Exception:
            # Non-fatal — some headless test environments don't
            # support cursor changes. The click still works.
            pass

        # Hover + click bindings. Use add="+" so we don't displace
        # any caller-installed bindings on the same events.
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<Button-1>", self._on_click_event, add="+")

    # ============================================================
    # HOVER HANDLERS
    # ============================================================

    def _on_enter(self, event=None):
        """<Enter> handler — lighten the text colour to indicate hover.

        P2-4: hover color now resolves via _hover_gold_for_current_theme()
        so it tracks the active theme (Office vs Fight Night) rather
        than being a hardcoded constant.

        Defensive — if the configure fails (headless test, destroyed
        widget), swallow silently. The hover effect is cosmetic; a
        failure here shouldn't crash the click handler.
        """
        try:
            self.configure(text_color=_hover_gold_for_current_theme())
        except Exception:
            pass

    def _on_leave(self, event=None):
        """<Leave> handler — restore the resting text colour."""
        try:
            self.configure(text_color=self._rest_color)
        except Exception:
            pass

    # ============================================================
    # CLICK HANDLER
    # ============================================================

    def _on_click_event(self, event=None):
        """<Button-1> handler — navigate to Fighter Profile + call on_click.

        Per AD-1: if `fighter_id` is set, navigate to the Fighter
        Profile screen for that fighter. The Fighter Profile screen
        is fetched from GameState (registered by CageEmpireApp at
        startup). If the screen isn't registered (defensive —
        shouldn't happen post-startup), log + fall through to the
        on_click callback.

        After (or instead of) the fighter navigation, call `on_click`
        if it was provided. The callback receives the fighter_id (or
        None) so it can do context-specific work.

        Defensive — any exception is logged but doesn't propagate.
        A broken hyperlink shouldn't crash the screen it lives in.
        """
        try:
            # ---- Fighter Profile navigation (if fighter_id set) ----
            if self._fighter_id is not None:
                state = get_state()
                profile_screen = state.get_screen("fighter_profile")
                if profile_screen is not None and hasattr(
                        profile_screen, "set_fighter_id"):
                    profile_screen.set_fighter_id(self._fighter_id)
                    state.set_active_screen("fighter_profile")
                else:
                    # Fighter Profile screen not registered — log +
                    # fall through to on_click (which might handle
                    # the click differently, e.g., open a popup).
                    print(
                        "Warning: HyperlinkLabel clicked but "
                        "'fighter_profile' screen is not registered "
                        "with GameState — navigation skipped.",
                        flush=True,
                    )
        except Exception as e:
            # Defensive — log but don't crash. A broken hyperlink
            # shouldn't take down the screen it lives in.
            print(f"Warning: HyperlinkLabel navigation failed: {e}",
                  flush=True)

        # ---- Custom on_click callback (always fires if set) ----
        # Fires AFTER the fighter navigation so the callback can
        # observe the new active screen if it wants to. Receives
        # the fighter_id (or None) as its sole argument.
        if self._on_click is not None:
            try:
                self._on_click(self._fighter_id)
            except Exception as e:
                print(f"Warning: HyperlinkLabel on_click failed: {e}",
                      flush=True)

    # ============================================================
    # PUBLIC API — caller can update fighter_id / on_click after init
    # ============================================================

    def set_fighter_id(self, fighter_id):
        """Update the fighter_id this link navigates to.

        Useful when the label is reused (e.g., a table row whose
        fighter changes on refresh).
        """
        self._fighter_id = fighter_id

    def set_on_click(self, on_click):
        """Update the custom click callback."""
        self._on_click = on_click
