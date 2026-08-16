"""CAGE EMPIRE — Phase 2 Component Library: Sparkline (§5.21).

Reusable mini line-chart.

Props:
  - data: list of numbers
  - width: default 120
  - height: default 32
  - color: default gold
  - fill_color: default gold_tint (semi-transparent)
  - show_min_max: bool, default False

Renders a line chart via PIL: normalize data to the width/height,
draw a smooth line (anti-aliased), fill below the line with semi-
transparent color. Optional min/max markers (small dots at the
lowest + highest points).

Cached: same data tuple returns the same CTkImage.

Use cases:
  - Dashboard cash flow (7-day)
  - Finance screen 30-day cash flow
  - Rankings rank movement (12-month)
  - Fighter Profile career arc
  - TrendIndicator (embedded)

CONVENTIONS compliance:
  §14 — Voice Layer: the data is NUMERIC (cash, rank position). Per
        §14, raw attribute values are banned from PLAYER-FACING UI,
        but cash + rank movement ARE shown as numbers (they're
        identity/career stats, not fighter attributes). The sparkline
        is a visualization of those numbers, not the numbers
        themselves — the screen shows the label + delta, the sparkline
        shows the SHAPE. This is consistent with how the spec uses
        sparklines (TrendIndicator embeds one for "delta context").
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, tint_to_solid
from ._pil_utils import make_ctk_sparkline, HAS_PIL


class Sparkline(ctk.CTkFrame):
    """A mini line chart.

    Args:
        parent: parent widget.
        data: list of numeric values. At least 2 points needed for a
            line; if < 2, the widget shows an empty frame (no line).
        width: pixel width. Default 120.
        height: pixel height. Default 32.
        line_color: hex color for the line. Defaults to theme gold.
        fill_color: rgba() or hex color for the area fill below the
            line. Defaults to gold_tint composited over the parent bg.
        show_min_max: if True, draw small dots at the min + max points.
        bg_color: optional bg color for the sparkline itself (rarely
            needed — usually the sparkline composites onto its parent).
        line_width: line stroke width in px. Default 2.
        **kwargs: forwarded to CTkFrame.

    The widget is a transparent CTkFrame holding a single CTkLabel
    with the PIL-rendered CTkImage. Callers can swap data at runtime
    via set_data().
    """

    def __init__(self, parent, data=None, width=120, height=32,
                 line_color=None, fill_color=None, show_min_max=False,
                 bg_color="rgba(0,0,0,0)", line_width=2, **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, width=width, height=height,
                         **kwargs)
        self._data = list(data) if data else []
        self._width = width
        self._height = height
        self._show_min_max = show_min_max
        self._bg_color = bg_color
        self._line_width = line_width

        theme = get_theme()
        c = theme.colors
        self._line_color = line_color or c.gold
        # Default fill: gold_tint composited over the parent's bg.
        if fill_color is None:
            try:
                self._fill_color = tint_to_solid(c.gold_tint, c.bg_card_elevated)
            except Exception:
                self._fill_color = "rgba(224,169,87,0.20)"
        else:
            self._fill_color = fill_color

        # The image label.
        self._img_label = ctk.CTkLabel(self, text="", anchor="center",
                                       fg_color="transparent")
        self._img_label.pack(fill="both", expand=True)

        # Try to lock the size.
        try:
            self.pack_propagate(False)
        except Exception:
            pass

        self._render()

    def _render(self):
        """Re-render the sparkline image + update the label."""
        if not HAS_PIL or len(self._data) < 2:
            try:
                self._img_label.configure(image=None)
            except Exception:
                pass
            return
        try:
            img = make_ctk_sparkline(
                self._data, self._width, self._height,
                self._line_color, self._fill_color,
                self._bg_color, self._show_min_max,
                self._line_width,
            )
            if img is not None:
                self._img_label.configure(image=img, text="")
            else:
                self._img_label.configure(image=None, text="—")
        except Exception:
            try:
                self._img_label.configure(image=None, text="—")
            except Exception:
                pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_data(self, data):
        """Update the data + re-render."""
        self._data = list(data) if data else []
        self._render()

    def set_color(self, line_color=None, fill_color=None):
        """Update colors + re-render."""
        if line_color is not None:
            self._line_color = line_color
        if fill_color is not None:
            self._fill_color = fill_color
        self._render()

    def set_show_min_max(self, show):
        self._show_min_max = bool(show)
        self._render()
