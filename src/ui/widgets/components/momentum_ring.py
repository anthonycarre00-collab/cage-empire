"""CAGE EMPIRE — Phase 2 Component Library: MomentumRing (§5.19).

Circular ring that fills clockwise based on momentum tier.

Props:
  - tier: one of (very_high, high, stable, falling, collapsing)
  - size: default 64
  - show_label: bool, default True

Renders a circular ring (PIL-drawn arc) that fills clockwise:
  very_high   = 100% gold
  high        = 75%  gold
  stable      = 50%  steel
  falling     = 25%  crimson
  collapsing  = 10%  crimson

Center label: the tier's SHORT voice phrase (e.g. "Scorching",
"Steady", "Sliding").

Background ring: border_subtle (unfilled portion).

Use cases:
  - Fighter Profile identity strip
  - Dashboard Watch Cards
  - Rankings contender highlights

CONVENTIONS compliance:
  §14 — Voice Layer: the ring shows a TIER (very_high → collapsing),
        not a raw number. The center label is a SHORT voice phrase.
        No raw attribute values anywhere.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme
from ._pil_utils import make_ctk_momentum_ring, HAS_PIL


# Tier → (fill_pct, color_key, short_label).
# Per UI_REDESIGN_VISUAL_PLAN §5.19:
#   very_high  = 100% gold        "Scorching"
#   high       = 75%  gold        "Hot"
#   stable     = 50%  steel       "Steady"
#   falling    = 25%  crimson     "Sliding"
#   collapsing = 10%  crimson     "Collapsing"
TIER_SPEC = {
    "very_high":   (1.00, "gold",    "Scorching"),
    "high":        (0.75, "gold",    "Hot"),
    "stable":      (0.50, "steel",   "Steady"),
    "falling":     (0.25, "crimson", "Sliding"),
    "collapsing":  (0.10, "crimson", "Collapsing"),
}


def _resolve_color(theme, key):
    """Resolve a color from theme + key."""
    c = theme.colors
    if key == "gold":
        return c.gold
    if key == "crimson":
        return c.crimson
    if key == "steel":
        return c.steel
    return c.gold


class MomentumRing(ctk.CTkFrame):
    """A circular momentum ring with a center label.

    Args:
        parent: parent widget.
        tier: one of very_high / high / stable / falling / collapsing.
        size: pixel diameter. Default 64.
        show_label: if True (default), show the tier's SHORT voice
            phrase in the center.
        thickness: ring stroke thickness in px. Default 6.
        custom_label: optional — override the center label. If None,
            uses the tier's short voice phrase.
        **kwargs: forwarded to CTkFrame.

    Layout (place-based):
      [ring image label, centered]
      [center text label, centered on top of the ring image]
    """

    def __init__(self, parent, tier="stable", size=64, show_label=True,
                 thickness=6, custom_label=None, **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, width=size, height=size,
                         **kwargs)
        self._tier = tier
        self._size = size
        self._show_label = show_label
        self._thickness = thickness
        self._custom_label = custom_label
        self._build()

    def _build(self):
        theme = get_theme()
        c = theme.colors
        spec = TIER_SPEC.get(self._tier, TIER_SPEC["stable"])
        fill_pct, color_key, default_label = spec
        color = _resolve_color(theme, color_key)
        bg = c.border_subtle

        # Ring image.
        if HAS_PIL:
            img = make_ctk_momentum_ring(
                size=self._size, fill_pct=fill_pct,
                color=color, bg_color=bg,
                thickness=self._thickness,
            )
            self._img_label = ctk.CTkLabel(
                self, image=img, text="", fg_color="transparent",
            )
        else:
            # PIL fallback: a single solid circle (no fill distinction).
            self._img_label = ctk.CTkLabel(
                self, text="●", font=(theme.fonts.h1[0], self._size - 8, "normal"),
                text_color=color, fg_color="transparent",
            )
        self._img_label.place(relx=0.5, rely=0.5, anchor="center",
                              relwidth=1.0, relheight=1.0)

        # Center label.
        if self._show_label:
            label_text = self._custom_label or default_label
            # Font size scales with ring size — small ring = small label.
            font_size = max(8, int(self._size * 0.18))
            self._center_label = ctk.CTkLabel(
                self, text=label_text,
                font=(theme.fonts.caption[0], font_size, "bold"),
                text_color=c.text_primary, fg_color="transparent",
            )
            self._center_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self._center_label = None

        try:
            self.pack_propagate(False)
        except Exception:
            pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_tier(self, tier, custom_label=None):
        """Update the tier + re-render."""
        for child in self.winfo_children():
            child.destroy()
        self._tier = tier
        if custom_label is not None:
            self._custom_label = custom_label
        self._build()

    def set_label(self, label):
        """Update just the center label text."""
        self._custom_label = label
        if self._center_label is not None:
            try:
                self._center_label.configure(text=label)
            except Exception:
                pass
