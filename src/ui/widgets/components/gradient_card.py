"""CAGE EMPIRE — Phase 2 Component Library: GradientCard (§5.16 / Group B).

Card with a PIL-composited gradient background.

Variants:
  - gold (top-left gold_tint → bottom-right transparent, for champion
    / accent cards)
  - crimson (for danger / rivalry cards)
  - steel (subtle grey gradient for default elevated cards)
  - custom (caller passes top_color + bottom_color)

The gradient is composited via PIL: create a 256×256 RGBA image, draw
a linear gradient, convert to CTkImage, set as the card's background
via a CTkLabel placed at the bottom of the pack order.

Cached: same (variant, size) combo returns the same CTkImage.

Border: 1px border_subtle (or 2px gold for gold variant, 2px crimson
for crimson variant).

Corner radius: 6px.

Use cases:
  - Dashboard Top Story (gold gradient)
  - Fighter Profile header (gold gradient if champion, steel if not)
  - Rivalries cards (crimson gradient for hot rivalries)

CONVENTIONS compliance:
  §14 — Voice Layer: the gradient is purely visual. The card's content
        (caller-packed children) carries the voice phrases.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, tint_to_solid, SPACE_LG
from ._pil_utils import make_ctk_gradient, HAS_PIL, parse_color


# Variant → (top_color, bottom_color, border_color, border_width).
# top_color is the "warm" corner; bottom_color is transparent so the
# gradient fades into the card's base bg.
def _resolve_variant(variant, theme, top_color=None, bottom_color=None):
    """Resolve (top, bottom, border_color, border_w) for the variant."""
    c = theme.colors
    if variant == "gold":
        # gold_tint composited over bg_card_elevated → a soft gold wash.
        top = tint_to_solid(c.gold_tint, c.bg_card_elevated)
        bot = c.bg_card_elevated
        return (top, bot, c.gold, 2)
    if variant == "crimson":
        top = tint_to_solid(c.crimson_tint, c.bg_card_elevated)
        bot = c.bg_card_elevated
        return (top, bot, c.crimson, 2)
    if variant == "steel":
        # Subtle grey gradient — top is bg_card_elevated (lighter),
        # bottom is bg_card (darker). Reads as a soft "elevation".
        top = c.bg_card_elevated
        bot = c.bg_card
        return (top, bot, c.border_subtle, 1)
    if variant == "custom":
        return (top_color or c.bg_card_elevated,
                bottom_color or c.bg_card,
                c.border_subtle, 1)
    # default = flat (no gradient)
    return (c.bg_card_elevated, c.bg_card_elevated,
            c.border_subtle, 1)


class GradientCard(ctk.CTkFrame):
    """A card with a PIL-composited gradient background.

    Args:
        parent: parent widget.
        variant: "gold" | "crimson" | "steel" | "custom" | "flat".
            gold     — top-left gold_tint → bottom-right transparent
                       (champion / accent cards).
            crimson  — top-left crimson_tint → bottom-right transparent
                       (danger / rivalry cards).
            steel    — subtle grey gradient (default elevated).
            custom   — caller passes top_color + bottom_color.
            flat     — no gradient (just bg_card_elevated).
        top_color: optional — for variant="custom".
        bottom_color: optional — for variant="custom".
        padding: inner content padding. Default SPACE_LG (16).
        corner_radius: 6px default.
        gradient_direction: "diagonal" (default) | "vertical" | "horizontal".
        gradient_size: PIL image size (default 256×256 — same image
            scales to any card size via CTkImage). Larger = sharper
            gradient but slower first-render. Keep at 256 for cache
            efficiency.
        **kwargs: forwarded to CTkFrame.

    Public API:
      card.content_frame — pack/grid children here.
      card.set_variant(variant) — switch variant at runtime.
    """

    DEFAULT_GRADIENT_SIZE = 256

    def __init__(self, parent, variant="gold", top_color=None,
                 bottom_color=None, padding=SPACE_LG,
                 corner_radius=6, gradient_direction="diagonal",
                 gradient_size=DEFAULT_GRADIENT_SIZE, **kwargs):
        super().__init__(parent, corner_radius=corner_radius, **kwargs)
        self._variant = variant
        self._top_color = top_color
        self._bottom_color = bottom_color
        self._padding = padding
        self._corner_radius = corner_radius
        self._gradient_direction = gradient_direction
        self._gradient_size = gradient_size
        self._bg_label = None

        # Inner content frame — callers pack/grid into this.
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True,
                                padx=padding, pady=padding)

        self._apply_style()

    def _apply_style(self):
        """Apply the gradient background + border for the variant."""
        theme = get_theme()
        top, bot, border_color, border_w = _resolve_variant(
            self._variant, theme, self._top_color, self._bottom_color
        )
        try:
            self.configure(
                fg_color=bot,  # Fallback if PIL fails
                border_color=border_color,
                border_width=border_w,
                corner_radius=self._corner_radius,
            )
        except Exception:
            pass

        # Compose the gradient image.
        if HAS_PIL and self._variant != "flat":
            try:
                img = make_ctk_gradient(
                    self._gradient_size, self._gradient_size,
                    top, bot, direction=self._gradient_direction,
                )
                if img is not None:
                    if self._bg_label is None:
                        self._bg_label = ctk.CTkLabel(
                            self, image=img, text="",
                            fg_color="transparent",
                        )
                        # Place at the BOTTOM of the stacking order so
                        # the content_frame stays on top.
                        self._bg_label.lower()
                        self._bg_label.place(relx=0, rely=0,
                                             relwidth=1.0, relheight=1.0)
                    else:
                        self._bg_label.configure(image=img)
            except Exception:
                pass
        else:
            # No PIL or flat variant — remove the bg label if any.
            if self._bg_label is not None:
                try:
                    self._bg_label.destroy()
                except Exception:
                    pass
                self._bg_label = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_variant(self, variant, top_color=None, bottom_color=None):
        """Switch variant at runtime. Re-renders the gradient."""
        self._variant = variant
        if top_color is not None:
            self._top_color = top_color
        if bottom_color is not None:
            self._bottom_color = bottom_color
        self._apply_style()

    def get_variant(self):
        return self._variant
