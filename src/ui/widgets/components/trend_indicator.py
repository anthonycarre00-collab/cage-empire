"""CAGE EMPIRE — Phase 2 Component Library: TrendIndicator (§5.17).

▲▼ arrow + delta value + optional sparkline.

Props:
  - current_value (int/float)
  - previous_value (int/float)
  - label (str, optional)
  - show_sparkline (bool, default True)
  - sparkline_data (list of 7 values, optional)

Arrow:
  ▲ (gold) if current > previous
  ▼ (crimson) if current < previous
  ● (steel) if equal

Delta:
  mono font, "+2.1M" or "-0.5M" or "0".

Sparkline:
  60×20 mini line chart (PIL-drawn), gold line, gold_tint fill below
  the line.

Use cases:
  - Dashboard cash trend
  - Fighter Profile rank movement
  - Rankings screen rank changes
  - StatTile (embedded)

CONVENTIONS compliance:
  §14 — Voice Layer: the delta VALUE is a number (cash, rank position)
        — these are identity/career stats, allowed per §14. The
        sparkline shows the SHAPE, not raw numbers. The label is a
        voice phrase (caller-provided).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, tint_to_solid, SPACE_SM, SPACE_XS
from .sparkline import Sparkline


def _format_delta(current, previous):
    """Format the delta as a signed string with M/K suffix."""
    try:
        delta = float(current) - float(previous)
    except (TypeError, ValueError):
        return "0"
    if delta == 0:
        return "0"
    sign = "+" if delta > 0 else "-"
    abs_d = abs(delta)
    if abs_d >= 1_000_000:
        return f"{sign}{abs_d / 1_000_000:.1f}M"
    if abs_d >= 1_000:
        return f"{sign}{abs_d / 1_000:.1f}K"
    if abs_d == int(abs_d):
        return f"{sign}{int(abs_d)}"
    return f"{sign}{abs_d:.1f}"


class TrendIndicator(ctk.CTkFrame):
    """A trend arrow + delta value + optional sparkline.

    Args:
        parent: parent widget.
        current_value: the current value (number).
        previous_value: the previous value (number). The arrow
            direction is computed from current vs previous.
        label: optional label text (e.g. "CASH"). If provided, shown
            to the left of the arrow.
        show_sparkline: if True (default), show a 60×20 sparkline to
            the right of the delta. If sparkline_data is None, the
            sparkline shows just [previous, current] as a 2-point
            line.
        sparkline_data: optional list of ≥2 values for the sparkline.
            If None, falls back to [previous, current].
        **kwargs: forwarded to CTkFrame.

    Layout (horizontal pack):
      [label] [arrow + delta] [sparkline]
    """

    def __init__(self, parent, current_value=0, previous_value=0,
                 label=None, show_sparkline=True, sparkline_data=None,
                 **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, **kwargs)
        self._current = current_value
        self._previous = previous_value
        self._label = label
        self._show_sparkline = show_sparkline
        self._sparkline_data = sparkline_data
        self._build()

    def _build(self):
        theme = get_theme()
        c = theme.colors

        try:
            cur = float(self._current)
            prev = float(self._previous)
        except (TypeError, ValueError):
            cur, prev = 0.0, 0.0

        if cur > prev:
            arrow = "▲"
            color = c.gold
            direction = "up"
        elif cur < prev:
            arrow = "▼"
            color = c.crimson
            direction = "down"
        else:
            arrow = "●"
            color = c.steel
            direction = "flat"

        # Optional label.
        if self._label:
            lbl = ctk.CTkLabel(
                self, text=self._label.upper(),
                font=theme.fonts.caption, text_color=c.text_secondary,
                anchor="w",
            )
            lbl.pack(side="left", padx=(0, SPACE_SM))

        # Arrow + delta group.
        group = ctk.CTkFrame(self, fg_color="transparent")
        group.pack(side="left")

        arrow_label = ctk.CTkLabel(
            group, text=arrow, font=theme.fonts.body,
            text_color=color, anchor="center",
        )
        arrow_label.pack(side="left", padx=(0, SPACE_XS))

        delta_text = _format_delta(cur, prev)
        delta_label = ctk.CTkLabel(
            group, text=delta_text, font=theme.fonts.mono,
            text_color=color, anchor="w",
        )
        delta_label.pack(side="left")

        # Optional sparkline.
        if self._show_sparkline:
            data = self._sparkline_data
            if data is None or len(data) < 2:
                data = [prev, cur]
            sparkline_color = (c.gold if direction == "up"
                               else c.crimson if direction == "down"
                               else c.steel)
            try:
                self._sparkline = Sparkline(
                    self, data=data, width=60, height=20,
                    line_color=sparkline_color,
                    fill_color=tint_to_solid(c.gold_tint, c.bg_card_elevated)
                    if direction == "up"
                    else tint_to_solid(c.crimson_tint, c.bg_card_elevated)
                    if direction == "down"
                    else "rgba(107,114,128,0.20)",
                )
                self._sparkline.pack(side="left", padx=(SPACE_SM, 0))
            except Exception:
                self._sparkline = None
        else:
            self._sparkline = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_values(self, current_value, previous_value,
                   sparkline_data=None):
        """Update the values + re-render."""
        # Destroy + rebuild — simplest approach for a small widget.
        for child in self.winfo_children():
            child.destroy()
        self._current = current_value
        self._previous = previous_value
        if sparkline_data is not None:
            self._sparkline_data = sparkline_data
        self._build()
