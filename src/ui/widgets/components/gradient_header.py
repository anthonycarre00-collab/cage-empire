"""CAGE EMPIRE — Phase 2 Component Library: GradientHeader (§5.24).

PIL gradient banner for screen titles.

Props:
  - title (str)
  - subtitle (str, optional)
  - variant ('gold' default, 'crimson', 'steel', 'custom')

Renders a horizontal banner (full-width, 64px tall) with a gradient
background: gold variant = gold (#e0a957) on the left → transparent
on the right; crimson = crimson → transparent; steel = bg_card_elevated
→ transparent.

Title: display_small (Oswald 24px), text_color = text_on_gold (for
gold variant) or text_primary (for steel variant).

Subtitle: caption UPPERCASE, text_color = text_on_gold at 70% opacity
(gold variant).

The gradient is PIL-composited (linear, left-to-right).

Use cases:
  - Every screen's H1 title bar. Replaces the current plain CTkLabel
    titles with a branded gradient banner.

CONVENTIONS compliance:
  §14 — Voice Layer: the title + subtitle are voice phrases
        (caller-provided per screen).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_LG, SPACE_XL
from ._pil_utils import make_ctk_gradient, HAS_PIL, parse_color


_HEADER_HEIGHT = 64
_GRADIENT_W = 1024  # Wide image — scaled by CTkImage to fit any width.


def _resolve_variant(variant, theme, top_color=None, bottom_color=None):
    """Resolve (gradient_top, gradient_bottom, text_color, subtitle_color)."""
    c = theme.colors
    if variant == "gold":
        # Gold band on the left, fading to transparent on the right.
        top = c.gold
        bot = c.bg_card_elevated  # Fades into the screen bg
        return (top, bot, c.text_on_gold, c.text_on_gold)
    if variant == "crimson":
        top = c.crimson
        bot = c.bg_card_elevated
        return (top, bot, c.text_on_crimson, c.text_on_crimson)
    if variant == "steel":
        # Subtle elevation gradient (no warm color).
        top = c.bg_card_elevated
        bot = c.bg_card
        return (top, bot, c.text_primary, c.text_secondary)
    if variant == "custom":
        return (top_color or c.bg_card_elevated,
                bottom_color or c.bg_card,
                c.text_primary, c.text_secondary)
    # default = steel
    return (c.bg_card_elevated, c.bg_card, c.text_primary, c.text_secondary)


class GradientHeader(ctk.CTkFrame):
    """A PIL-gradient banner for screen H1 titles.

    Args:
        parent: parent widget.
        title: the screen title text (display_small). Will be
            uppercased.
        subtitle: optional subtitle (caption UPPERCASE).
        variant: "gold" | "crimson" | "steel" | "custom". Default
            "gold".
        top_color, bottom_color: optional — for variant="custom".
        height: banner height in px. Default 64.
        **kwargs: forwarded to CTkFrame.

    Layout (place-based):
      [gradient bg label, full size, bottom of stack]
      [content frame on top: title (left) + subtitle (right or below)]
    """

    def __init__(self, parent, title="", subtitle=None, variant="gold",
                 top_color=None, bottom_color=None, height=_HEADER_HEIGHT,
                 **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, height=height, **kwargs)
        self._title = title
        self._subtitle = subtitle
        self._variant = variant
        self._top_color = top_color
        self._bottom_color = bottom_color
        self._height = height

        theme = get_theme()
        top, bot, text_color, sub_color = _resolve_variant(
            variant, theme, top_color, bottom_color)

        # Lock the height.
        try:
            self.pack_propagate(False)
        except Exception:
            pass

        # Gradient background label.
        if HAS_PIL:
            try:
                img = make_ctk_gradient(
                    _GRADIENT_W, height, top, bot,
                    direction="horizontal",
                )
                if img is not None:
                    self._bg_label = ctk.CTkLabel(
                        self, image=img, text="",
                        fg_color="transparent",
                    )
                    self._bg_label.place(relx=0, rely=0,
                                         relwidth=1.0, relheight=1.0)
                else:
                    # PIL failed — solid color fallback.
                    self.configure(fg_color=top)
                    self._bg_label = None
            except Exception:
                self.configure(fg_color=top)
                self._bg_label = None
        else:
            # No PIL — solid color fallback.
            self.configure(fg_color=top)
            self._bg_label = None

        # Content frame on top.
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        # Pad the content from the left.
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Title label (left, vertically centered).
        self._title_label = ctk.CTkLabel(
            content, text=(title or "").upper(),
            font=theme.fonts.display_small, text_color=text_color,
            anchor="w", padx=SPACE_XL,
        )
        self._title_label.grid(row=0, column=0, sticky="ew")

        # Subtitle (right side).
        if subtitle:
            self._subtitle_label = ctk.CTkLabel(
                content, text=subtitle.upper(),
                font=theme.fonts.caption, text_color=sub_color,
                anchor="e", padx=SPACE_XL,
            )
            self._subtitle_label.grid(row=0, column=1, sticky="ew")
        else:
            self._subtitle_label = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_title(self, title):
        try:
            self._title_label.configure(text=(title or "").upper())
        except Exception:
            pass

    def set_subtitle(self, subtitle):
        try:
            if subtitle:
                if self._subtitle_label is None:
                    theme = get_theme()
                    _, _, _, sub_color = _resolve_variant(
                        self._variant, theme, self._top_color,
                        self._bottom_color)
                    self._subtitle_label = ctk.CTkLabel(
                        self, text=subtitle.upper(),
                        font=theme.fonts.caption, text_color=sub_color,
                        anchor="e", padx=SPACE_XL,
                    )
                    self._subtitle_label.place(relx=1.0, rely=0.5,
                                               anchor="e", relwidth=0.5)
                else:
                    self._subtitle_label.configure(text=subtitle.upper())
            elif self._subtitle_label is not None:
                self._subtitle_label.destroy()
                self._subtitle_label = None
        except Exception:
            pass
