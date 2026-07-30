"""CAGE EMPIRE — Phase 2 Component Library: HyperlinkLabel (§5.9).

Refines the gold-text clickable label.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.9):

  - Default text color: gold (#e0a957)
  - Hover text color: gold_bright (#f5c878)
  - Underline: 1px, gold_tint (40% opacity), appears on hover only
  - Cursor: hand2 on hover
  - Font: inherits parent context (usually body_small Bold for fighter
    names)

States:
  Default → hover (color + underline, 100ms) → pressed (color briefly
  drops to gold with -10% lightness) → visited (kept at default gold —
  no visited state to avoid clutter).

When to use:
  Fighter names everywhere. Card titles that link to detail views.
  "View all" links at the bottom of card sections.

When NOT to use:
  For buttons (use Button, §5.10). For tabs (use TabBar, §5.11).

NOTE: This is the Phase 2 refactor of the existing
src/ui/widgets/hyperlink.py. The old module stays for back-compat
until Phases 3-6 migrate screens to use this version. The two
implementations share the same look + feel; this version lives in
the components/ package for consistency with the other 23 components.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme


class HyperlinkLabel(ctk.CTkLabel):
    """A gold-text clickable label that navigates to Fighter Profile.

    Args:
        parent: parent widget.
        text: the link text (typically a fighter name).
        fighter_id: optional int — clicking navigates to the Fighter
            Profile screen for this fighter.
        on_click: optional callable — invoked AFTER the fighter
            navigation. Receives the fighter_id as its sole argument
            (or None).
        underline_on_hover: bool — if True (default), the text gets
            an underline on hover. Implemented as a font toggle
            (underline=True vs underline=False) since CTk doesn't
            expose CSS-style text-decoration.
        **kwargs: forwarded to CTkLabel. Defaults: text_color=gold,
            font=body.

    Click behaviour:
      If fighter_id is set, the click navigates to the Fighter Profile
      screen via GameState. If on_click is also set, it fires after
      the navigation. If only on_click is set (no fighter_id), the
      click fires on_click(None).
    """

    def __init__(self, parent, text="", fighter_id=None, on_click=None,
                 underline_on_hover=True, **kwargs):
        theme = get_theme()
        kwargs.setdefault("text_color", theme.colors.gold)
        kwargs.setdefault("font", theme.fonts.body)
        super().__init__(parent, text=text, **kwargs)

        self._fighter_id = fighter_id
        self._on_click = on_click
        self._rest_color = kwargs["text_color"]
        self._rest_font = kwargs["font"]
        self._underline_on_hover = underline_on_hover

        # Underlined font variant (same family/size/weight + underline).
        # The font tuple is (family, size, weight); we append
        # "underline" via a 4th element if supported, else swap the
        # weight to include underline via Tk font config.
        self._hover_font = self._make_underlined(self._rest_font)

        try:
            self.configure(cursor="hand2")
        except Exception:
            pass

        try:
            self.bind("<Enter>", self._on_enter, add="+")
            self.bind("<Leave>", self._on_leave, add="+")
            self.bind("<Button-1>", self._on_click_event, add="+")
        except Exception:
            pass

    def _make_underlined(self, font_tuple):
        """Return a copy of font_tuple with underline added.

        Tk font tuples support a 4th element for underline + overstrike.
        We append "underline" — Tk accepts (family, size, weight,
        underline). If the caller's font is a TkFont object, we
        configure underline=True via copy().
        """
        try:
            if isinstance(font_tuple, (tuple, list)):
                if len(font_tuple) >= 4:
                    return tuple(font_tuple)
                # Append "underline" — Tk interprets the 4th element
                # as a boolean-ish underline flag.
                return tuple(font_tuple) + (True,)
            # TkFont — copy + configure.
            from tkinter import font as tkfont
            new_font = tkfont.Font(font=font_tuple)
            new_font.configure(underline=True)
            return new_font
        except Exception:
            return font_tuple

    # ------------------------------------------------------------
    # HOVER HANDLERS
    # ------------------------------------------------------------

    def _on_enter(self, event=None):
        try:
            theme = get_theme()
            self.configure(text_color=theme.colors.gold_bright)
            if self._underline_on_hover:
                self.configure(font=self._hover_font)
        except Exception:
            pass

    def _on_leave(self, event=None):
        try:
            self.configure(text_color=self._rest_color)
            if self._underline_on_hover:
                self.configure(font=self._rest_font)
        except Exception:
            pass

    # ------------------------------------------------------------
    # CLICK HANDLER
    # ------------------------------------------------------------

    def _on_click_event(self, event=None):
        try:
            if self._fighter_id is not None:
                from ui.state import get_state
                state = get_state()
                profile_screen = state.get_screen("fighter_profile")
                if profile_screen is not None and hasattr(
                        profile_screen, "set_fighter_id"):
                    profile_screen.set_fighter_id(self._fighter_id)
                    state.set_active_screen("fighter_profile")
                else:
                    print("Warning: components.HyperlinkLabel clicked "
                          "but 'fighter_profile' screen not registered.",
                          flush=True)
        except Exception as e:
            print(f"Warning: HyperlinkLabel navigation failed: {e}",
                  flush=True)

        if self._on_click is not None:
            try:
                self._on_click(self._fighter_id)
            except Exception as e:
                print(f"Warning: HyperlinkLabel on_click failed: {e}",
                      flush=True)

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_fighter_id(self, fighter_id):
        self._fighter_id = fighter_id

    def set_on_click(self, on_click):
        self._on_click = on_click
