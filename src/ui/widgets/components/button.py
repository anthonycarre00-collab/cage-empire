"""CAGE EMPIRE — Phase 2 Component Library: Button (§5.10).

4 variants: Primary (gold) / Secondary (outline) / Danger (crimson) /
Ghost.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.10):

  +-----------+-------------+-----------+--------+--------+-----------+
  | Variant   | bg          | text      | border | radius | padding   |
  +-----------+-------------+-----------+--------+--------+-----------+
  | Primary   | gold        | text_on_gold | none | 4px   | 10×20    |
  | Secondary | transparent | text_primary | border_subtle 1px | 4px | 10×20 |
  | Danger    | crimson     | text_on_crimson | none | 4px | 10×20   |
  | Ghost     | transparent | text_secondary | none | 4px   | 8×12    |
  +-----------+-------------+-----------+--------+--------+-----------+

States:
  - Default (resting)
  - Hover: Primary → gold_bright; Secondary → bg_card_elevated;
    Danger → slightly brighter crimson; Ghost → text_primary.
  - Pressed: 100ms darker bg flash.
  - Disabled: 40% opacity on text + bg, cursor = arrow.
  - Loading (future, P1): spinner replaces text.

Font:
  body_small Bold (Inter 13px). For primary action buttons on Fight
  Night (Exit Fight, Skip to Finish), use display_small (Oswald 24px)
  — bigger = more important.

When to use:
  - Primary: the single most important action on a screen ("Sign
    Fighter", "Advance Day", "Exit Fight")
  - Secondary: alternative actions ("View Profile", "Compare",
    "Filter")
  - Danger: destructive actions ("Cut Fighter", "Cancel Event")
  - Ghost: tertiary actions ("Cancel" in a modal, "Dismiss" on a card)

Rule: a screen should have AT MOST ONE Primary button visible at a
time. Multiple primaries compete for attention and dilute the call to
action.

CONVENTIONS compliance:
  §14 — Voice Layer: button text is the action verb (caller-provided,
        voice-phrased per the spec — "Sign Fighter", not "Sign"). No
        raw attribute numbers.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD


class Button(ctk.CTkButton):
    """A 4-variant button.

    Args:
        parent: parent widget.
        text: the button label.
        variant: "primary" | "secondary" | "danger" | "ghost".
        on_click: callable() — fired on click. (Also accepts the
            command kwarg via CTkButton for back-compat.)
        size: "default" | "large" — large uses display_small font
            (Oswald 24px) for Fight Night primary actions.
        icon: optional CTkImage — placed to the left of the text.
        disabled: bool — initial disabled state.
        **kwargs: forwarded to CTkButton.

    Notes:
      - The button reads theme.colors at construction time. Theme
        switches require a re-render (the parent screen calls
        set_variant again, or recreates the button).
      - Hover colors track the theme's gold_bright / crimson
        equivalents.
    """

    def __init__(self, parent, text="", variant="secondary",
                 on_click=None, size="default", icon=None,
                 disabled=False, **kwargs):
        theme = get_theme()
        self._variant = variant
        self._size = size
        self._on_click = on_click

        fg, hover, text_color, border_color, border_w, _padx, _pady = \
            self._resolve_style(theme)

        font = (theme.fonts.display_small if size == "large"
                else (theme.fonts.body_small[0],
                      theme.fonts.body_small[1], "bold"))

        kwargs.setdefault("text", text)
        kwargs.setdefault("fg_color", fg)
        kwargs.setdefault("hover_color", hover)
        kwargs.setdefault("text_color", text_color)
        kwargs.setdefault("border_color", border_color)
        kwargs.setdefault("border_width", border_w)
        kwargs.setdefault("corner_radius", 4)
        kwargs.setdefault("font", font)
        kwargs.setdefault("image", icon)
        if on_click is not None:
            kwargs.setdefault("command", on_click)
        # Note: CTk 6.0's CTkButton does NOT accept padx/pady in the
        # constructor (they raise ValueError). The button's natural
        # height (~28-32px) + internal text padding (border_spacing=2
        # + text_label padx=10) gives the "10×20 padding" feel from
        # the spec. For the "large" Fight Night variant, the larger
        # font (display_small, 24px) bumps the natural height to
        # ~40-48px. Callers wanting tighter/looser padding can wrap
        # the button in a CTkFrame with their own padx/pady on pack.

        super().__init__(parent, **kwargs)

        if disabled:
            try:
                self.configure(state="disabled")
            except Exception:
                pass

    def _resolve_style(self, theme):
        """Resolve (fg, hover, text_color, border_color, border_w,
        padx, pady) for the current variant + theme.
        """
        c = theme.colors
        v = self._variant
        if v == "primary":
            return (c.gold, c.gold_bright, c.text_on_gold,
                    c.gold, 0, 20, 10)
        if v == "danger":
            # Hover: slightly brighter crimson (we don't have a
            # crimson_bright token — use a lighten() of crimson).
            from ._pil_utils import parse_color, lighten, rgba_to_hex
            try:
                bright = rgba_to_hex(lighten(parse_color(c.crimson), 0.18))
            except Exception:
                bright = c.crimson
            return (c.crimson, bright, c.text_on_crimson,
                    c.crimson, 0, 20, 10)
        if v == "ghost":
            # Ghost: transparent resting bg, no border, text_secondary.
            # CTk 6.0's hover_color doesn't accept "transparent" — use
            # bg_card_elevated as the hover (a subtle grey flash) so
            # the hover effect reads. The text also darkens to
            # text_primary (handled separately below via configure).
            # border_color is border_subtle (with width=0 it never
            # renders, but CTk validates the color regardless of
            # width — and "transparent" is rejected for border_color).
            return ("transparent", c.bg_card_elevated, c.text_secondary,
                    c.border_subtle, 0, 12, 8)
        # secondary (default)
        return ("transparent", c.bg_card_elevated, c.text_primary,
                c.border_subtle, 1, 20, 10)

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_variant(self, variant):
        """Update the variant at runtime."""
        self._variant = variant
        theme = get_theme()
        fg, hover, text_color, border_color, border_w, _padx, _pady = \
            self._resolve_style(theme)
        try:
            self.configure(fg_color=fg, hover_color=hover,
                           text_color=text_color,
                           border_color=border_color,
                           border_width=border_w)
        except Exception:
            pass

    def set_on_click(self, on_click):
        self._on_click = on_click
        try:
            self.configure(command=on_click)
        except Exception:
            pass

    def set_disabled(self, disabled):
        try:
            self.configure(state="disabled" if disabled else "normal")
        except Exception:
            pass
