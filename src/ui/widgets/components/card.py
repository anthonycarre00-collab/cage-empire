"""CAGE EMPIRE — Phase 2 Component Library: Card (§5.1).

The base surface for every content block. 3 variants per the
UI_REDESIGN_VISUAL_PLAN §5.1:

  +-----------+----------+------------+----------+--------+----------+
  | Variant   | bg       | border     | radius   | pad    | Min size |
  +-----------+----------+------------+----------+--------+----------+
  | Flat      | bg_card  | border_subtle 1px | 6px | 16px | 200×100  |
  | Elevated  | bg_card_elevated | border_subtle 1px | 6px | 16px | 200×100 |
  | Accent    | bg_card  | border_strong 2px gold | 6px | 16px | 200×100 |
  +-----------+----------+------------+----------+--------+----------+

States: Flat (resting) → Elevated (hover, 100ms transition) → Accent
(when "selected" or "marked important" by parent screen).

NOTE: per the contrast fix from commit f48ec52, card backgrounds use
`bg_card_elevated` (the LIGHTEST tier, lum 42) for visibility against
the shell. The Phase 1.5 quick-wins work established this — Phase 2
components inherit that fix as the default. Callers can still request
`bg_card` (the darker tier) explicitly via `bg_tier="card"` if they
need it (rare — only when nested inside an Elevated card).

When to use:
  Default for ALL content blocks. The screen is a grid of Cards.
  The ONLY things on a screen that aren't Cards are: the screen H1,
  the filter row, the table (which is a Card variant with sharp
  corners), and the action bar.

When NOT to use:
  For modal dialogs (use ModalDialog, §5.16). For table rows (use
  FighterRow, §5.5). For chips (use DataChip, §5.4).

CONVENTIONS compliance:
  §14 — Voice Layer: Card itself doesn't display text. Children do.
  §17 — UI Snapshot Rule: no DB reads. Pure layout surface.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_LG


class Card(ctk.CTkFrame):
    """The base surface for every content block. 3 variants.

    Args:
        parent: parent widget.
        variant: "flat" (default) | "elevated" | "accent".
            flat    — bg_card_elevated bg, border_subtle 1px (the
                      default visible card tier).
            elevated — bg_card_elevated bg, border_subtle 1px (same
                       as flat — kept as a separate variant name so
                       callers can request "elevated" semantically
                       even if the contrast fix is later tuned).
            accent  — bg_card_elevated bg, gold border_strong 2px.
        padding: inner padding in px. Defaults to SPACE_LG (16).
        corner_radius: 6px default.
        hover_elevate: if True, hovering the card bumps its border
            to gold 2px (a subtle hover affordance). Defaults False
            (callers opt in — most cards don't want hover effects).
        accent_color: optional — overrides the accent border color
            (default gold). Used for crimson accent cards (e.g.,
            Biggest Fall WatchCard).
        **kwargs: forwarded to CTkFrame.

    Public API:
      card.content_frame — the inner frame callers should pack/grid
        their content into. Has `padding` of inner padding.
      card.set_variant(variant) — switch variant at runtime
        (used by hover handlers / selection state).
    """

    def __init__(self, parent, variant="flat", padding=SPACE_LG,
                 corner_radius=6, hover_elevate=False,
                 accent_color=None, **kwargs):
        super().__init__(parent, corner_radius=corner_radius, **kwargs)
        self._variant = variant
        self._padding = padding
        self._corner_radius = corner_radius
        self._hover_elevate = hover_elevate
        self._accent_color = accent_color
        self._rest_variant = variant  # for hover restore

        # Inner content frame — callers pack/grid into this.
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True,
                                padx=padding, pady=padding)

        self._apply_style()

        if hover_elevate:
            try:
                self.bind("<Enter>", self._on_enter, add="+")
                self.bind("<Leave>", self._on_leave, add="+")
            except Exception:
                pass

    # ------------------------------------------------------------
    # STYLE APPLICATION
    # ------------------------------------------------------------

    def _apply_style(self):
        """Read theme + apply bg + border for the current variant."""
        theme = get_theme()
        c = theme.colors
        if self._variant == "accent":
            fg = c.bg_card_elevated
            border_color = self._accent_color or c.gold
            border_width = 2
        elif self._variant == "elevated":
            fg = c.bg_card_elevated
            border_color = c.border_subtle
            border_width = 1
        else:  # flat
            fg = c.bg_card_elevated
            border_color = c.border_subtle
            border_width = 1
        try:
            self.configure(
                fg_color=fg,
                border_color=border_color,
                border_width=border_width,
                corner_radius=self._corner_radius,
            )
        except Exception:
            pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_variant(self, variant):
        """Switch the card variant at runtime."""
        self._variant = variant
        self._rest_variant = variant
        self._apply_style()

    def get_variant(self) -> str:
        return self._variant

    # ------------------------------------------------------------
    # HOVER HANDLERS
    # ------------------------------------------------------------

    def _on_enter(self, event=None):
        """Hover → bump border to gold (subtle affordance)."""
        if not self._hover_elevate:
            return
        try:
            theme = get_theme()
            self.configure(border_color=theme.colors.gold,
                           border_width=2)
        except Exception:
            pass

    def _on_leave(self, event=None):
        """Restore resting border."""
        if not self._hover_elevate:
            return
        self._apply_style()
