"""CAGE EMPIRE — Phase 2 Component Library: StatTile (§5.22).

Large number + trend arrow + sparkline.

Props:
  - label (str, e.g. "CASH")
  - value (str, e.g. "$50.0M")
  - trend (TrendIndicator instance, optional)
  - sparkline (Sparkline instance, optional)

Layout:
  label (top, caption UPPERCASE)
  value (center, display_small mono)
  trend + sparkline (bottom)

Card variant: Flat, 4-col width, 6px radius.

Use cases:
  - Dashboard Promotion Status (cash, reputation, fan trust, roster,
    champions = 5 StatTiles)
  - Finance screen summary cards

CONVENTIONS compliance:
  §14 — Voice Layer: the value is a number (cash, count) — these are
        identity/career stats, allowed per §14. The label is a voice
        phrase (uppercase caption). The trend + sparkline are
        visualizations of the number, not raw attribute values.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD, SPACE_LG
from .card import Card


class StatTile(Card):
    """A large-number stat tile with optional trend + sparkline.

    Args:
        parent: parent widget.
        label: the label text (caption UPPERCASE). E.g. "CASH".
        value: the value text (display_small mono). E.g. "$50.0M".
        trend_widget: optional TrendIndicator instance. Pass None to
            skip. NOTE: the caller must create the TrendIndicator with
            `parent=self.content_frame` AFTER constructing the StatTile
            (or use set_trend() below). For simplicity, StatTile
            accepts the trend DATA and builds its own TrendIndicator.
        current_value, previous_value, sparkline_data: optional — if
            provided, StatTile builds a TrendIndicator + Sparkline
            internally. If trend_widget is provided, these are ignored.
        show_sparkline: bool — only used when current_value +
            previous_value are provided (controls whether the embedded
            TrendIndicator shows its sparkline).
        **kwargs: forwarded to Card (default variant=flat).

    Inherits from Card.
    """

    def __init__(self, parent, label="", value="",
                 trend_widget=None, current_value=None,
                 previous_value=None, sparkline_data=None,
                 show_sparkline=True, **kwargs):
        kwargs.setdefault("variant", "flat")
        super().__init__(parent, **kwargs)

        theme = get_theme()
        c = theme.colors

        # Label (top).
        self._label = ctk.CTkLabel(
            self.content_frame, text=label.upper(),
            font=theme.fonts.caption, text_color=c.text_secondary,
            anchor="w",
        )
        self._label.pack(anchor="w", pady=(0, SPACE_SM))

        # Value (center).
        self._value = ctk.CTkLabel(
            self.content_frame, text=value,
            font=theme.fonts.mono, text_color=c.text_primary,
            anchor="w",
        )
        self._value.pack(anchor="w", pady=(0, SPACE_SM))

        # Trend + sparkline (bottom).
        if trend_widget is not None:
            # Caller-provided widget — reparent (or assume the caller
            # already parented it correctly). For simplicity, we
            # re-pack it inside our content_frame.
            try:
                trend_widget.pack(in_=self.content_frame, anchor="w",
                                  side="top")
            except Exception:
                pass
            self._trend = trend_widget
        elif current_value is not None and previous_value is not None:
            # Build our own TrendIndicator.
            try:
                from .trend_indicator import TrendIndicator
                self._trend = TrendIndicator(
                    self.content_frame,
                    current_value=current_value,
                    previous_value=previous_value,
                    show_sparkline=show_sparkline,
                    sparkline_data=sparkline_data,
                )
                self._trend.pack(anchor="w")
            except Exception:
                self._trend = None
        else:
            self._trend = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_value(self, value):
        try:
            self._value.configure(text=value)
        except Exception:
            pass

    def set_label(self, label):
        try:
            self._label.configure(text=label.upper())
        except Exception:
            pass

    def set_trend_values(self, current, previous, sparkline_data=None):
        """Re-build the embedded TrendIndicator with new values."""
        if self._trend is not None:
            try:
                self._trend.set_values(current, previous, sparkline_data)
            except Exception:
                pass
