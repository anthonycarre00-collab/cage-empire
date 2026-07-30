"""CAGE EMPIRE — Phase 2 Component Library: DataChip (§5.3).

Small status pill for "champion", "injured", "on streak", etc.
Replaces the inline text badges scattered across screens.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.3):

  +-----------+----------+-----------+--------+----------+----------+
  | Variant   | bg       | text      | border | radius   | padding  |
  +-----------+----------+-----------+--------+----------+----------+
  | Default   | bg_card_elevated | text_secondary | none | 4px | 4×8 |
  | Champion  | gold_tint | gold     | gold 1px | 4px    | 4×8     |
  | Danger    | crimson_tint | crimson | crimson 1px | 4px | 4×8   |
  | Info      | rgba(96,165,250,0.10) | info | info 1px | 4px | 4×8 |
  +-----------+----------+-----------+--------+----------+----------+

  Text: caption (Inter 11px uppercase +0.04em). ALWAYS UPPERCASE.

States:
  Default → hover (bg_card_elevated bg, 100ms) → pressed (slightly darker).

When to use:
  Inline with fighter names (champion chip), in tables (injured chip),
  on Dashboard watch cards (streak chip), on news cards (topic chip).

When NOT to use:
  For primary actions (use Button, §5.10). For section labels (use
  SectionHeader, §5.2).

CONVENTIONS compliance:
  §14 — Voice Layer: chip text is caller-provided (e.g. "CHAMP",
        "INJ", "W3"). No raw attribute numbers.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, tint_to_solid, SPACE_XS, SPACE_SM


class DataChip(ctk.CTkLabel):
    """A small status pill. 4 variants.

    Args:
        parent: parent widget.
        text: the chip text (will be uppercased).
        variant: "default" | "champion" | "danger" | "info".
        **kwargs: forwarded to CTkLabel.

    The chip is a CTkLabel (not CTkFrame) so it sizes naturally to
    its text. Padding is achieved via padx/pady on the label.
    """

    def __init__(self, parent, text="", variant="default", **kwargs):
        theme = get_theme()
        self._variant = variant
        fg, border, border_w, text_color = self._resolve_style(theme)
        kwargs.setdefault("fg_color", fg)
        kwargs.setdefault("border_color", border)
        kwargs.setdefault("border_width", border_w)
        kwargs.setdefault("corner_radius", 4)
        kwargs.setdefault("text_color", text_color)
        kwargs.setdefault("font", theme.fonts.caption)
        kwargs.setdefault("anchor", "center")
        kwargs.setdefault("padx", SPACE_SM)
        kwargs.setdefault("pady", SPACE_XS)
        super().__init__(parent, text=str(text).upper(), **kwargs)

    def _resolve_style(self, theme):
        """Resolve (bg, border_color, border_width, text_color) for
        the current variant + theme.

        Tints (gold_tint / crimson_tint / info rgba) are composited
        over bg_card_elevated via tint_to_solid so CTk gets a solid
        hex it can render.
        """
        c = theme.colors
        v = self._variant
        if v == "champion":
            fg = tint_to_solid(c.gold_tint, c.bg_card_elevated)
            return (fg, c.gold, 1, c.gold)
        if v == "danger":
            fg = tint_to_solid(c.crimson_tint, c.bg_card_elevated)
            return (fg, c.crimson, 1, c.crimson)
        if v == "info":
            info_tint = "rgba(96,165,250,0.10)"
            fg = tint_to_solid(info_tint, c.bg_card_elevated)
            return (fg, c.info, 1, c.info)
        # default
        return (c.bg_card_elevated, c.border_subtle, 0, c.text_secondary)

    def set_variant(self, variant):
        """Update the chip variant at runtime."""
        self._variant = variant
        theme = get_theme()
        fg, border, border_w, text_color = self._resolve_style(theme)
        try:
            self.configure(fg_color=fg, border_color=border,
                           border_width=border_w, text_color=text_color)
        except Exception:
            pass

    def set_text(self, text):
        """Update the chip text. Uppercased automatically."""
        try:
            self.configure(text=str(text).upper())
        except Exception:
            pass
