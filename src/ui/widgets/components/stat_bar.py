"""CAGE EMPIRE — Phase 2 Component Library: StatBar (§5.4).

Horizontal bar for attribute visualization. Voice-encoded, NOT raw
numbers. Per CONVENTIONS §14, the bar shows the *voice tier* (7
tiers: abysmal → exceptional), not the 0-100 value.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.4):

    Striking Power      ████████████████░░░░░░  carries real knockout power

  - Label (left, 140px): body_small, text_secondary
  - Bar (center, fills available): 8px tall, bg_card_elevated track,
    fill = gold (default) | crimson (abysmal/poor) | info (elite/
    exceptional — sparingly to avoid green-vs-blue confusion).
  - Bar fill width: tier-based (abysmal=8%, poor=22%, below_avg=36%,
    avg=50%, above_avg=64%, good=78%, elite=92%, exceptional=100%).
  - Voice phrase (right, 200px): descriptor italic, text_primary.

States:
  Hover → show tooltip with the FULL long-form descriptor.

When to use:
  Fighter Profile attribute grid (26 bars). Scouting Report projected
  attributes. Personality grid (20 bars).

When NOT to use:
  For numeric values (cash, record, ranking position) — use plain
  `mono` text. StatBar is for ATTRIBUTE TIERS, not numbers.

NOTE: This is the SIMPLE (non-animated) attribute bar. For the
animated version with tier color coding + tooltip, use AttributeBar
(§5.20 / attribute_bar.py). StatBar is kept as the legacy non-
animated variant for screens that don't want the animation overhead.

CONVENTIONS compliance:
  §14 — Voice Layer: NO raw numbers shown. The bar shows the voice
        TIER (which translates to a fill width) and the voice PHRASE.
        Hover tooltip shows the LONG voice phrase (caller-provided).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM
from ._tooltip import HoverTooltip


# Tier → fill percent + bar color tier.
# Per UI_REDESIGN_VISUAL_PLAN §5.4:
#   abysmal=8%, poor=22%, below_avg=36%, avg=50%, above_avg=64%,
#   good=78%, elite=92%, exceptional=100%.
TIER_FILL_PCT = {
    "abysmal":      0.08,
    "poor":         0.22,
    "below_avg":    0.36,
    "avg":          0.50,
    "above_avg":    0.64,
    "good":         0.78,
    "elite":        0.92,
    "exceptional":  1.00,
}

# Color tier by attribute tier.
#   abysmal, poor → crimson (warning)
#   below_avg, avg → steel (neutral)
#   above_avg, good, elite → gold (positive)
#   exceptional → champion_gold (rare, max)
TIER_COLOR_KEY = {
    "abysmal":      "crimson",
    "poor":         "crimson",
    "below_avg":    "steel",
    "avg":          "steel",
    "above_avg":    "gold",
    "good":         "gold",
    "elite":        "gold",
    "exceptional":  "champion_gold",
}


def _resolve_tier_color(theme, tier: str):
    """Resolve a bar color from theme + tier name."""
    c = theme.colors
    key = TIER_COLOR_KEY.get(tier, "gold")
    if key == "crimson":
        return c.crimson
    if key == "steel":
        return c.steel
    if key == "champion_gold":
        # Fall back to theme gold if CHAMPIONSHIP_SKIN import fails.
        try:
            from ui.theme import CHAMPIONSHIP_SKIN
            return CHAMPIONSHIP_SKIN.get("champion_gold", c.gold_bright)
        except Exception:
            return c.gold_bright
    return c.gold


class StatBar(ctk.CTkFrame):
    """Horizontal voice-encoded attribute bar. 7 tiers.

    Args:
        parent: parent widget.
        label: the attribute name (e.g. "Striking Power").
        tier: one of abysmal/poor/below_avg/avg/above_avg/good/elite/
            exceptional.
        voice_phrase: the SHORT voice descriptor shown next to the bar
            (e.g. "carries real knockout power").
        long_phrase: optional LONG voice descriptor shown in the
            hover tooltip (per the audit doc's proposed short/long
            variant system). If None, the tooltip shows the short
            phrase.
        label_width: left label column width in px. Default 140.
        voice_width: right voice-phrase column width in px. Default 200.
        bar_height: bar fill height in px. Default 8.
        **kwargs: forwarded to CTkFrame.

    Layout (grid, 3 columns):
      [label | bar track + fill | voice phrase]
    """

    def __init__(self, parent, label="", tier="avg", voice_phrase="",
                 long_phrase=None, label_width=140, voice_width=200,
                 bar_height=8, **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, **kwargs)
        theme = get_theme()
        self._tier = tier
        self._label_text = label
        self._voice_phrase = voice_phrase
        self._long_phrase = long_phrase or voice_phrase
        self._label_width = label_width
        self._voice_width = voice_width
        self._bar_height = bar_height

        # Column 0: attribute label.
        self._label = ctk.CTkLabel(
            self, text=label,
            font=theme.fonts.body_small,
            text_color=theme.colors.text_secondary,
            anchor="w", width=label_width,
        )
        self._label.grid(row=0, column=0, sticky="w", padx=(0, SPACE_SM))

        # Column 1: bar track + fill.
        self._track = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_card_elevated,
            corner_radius=2, height=bar_height,
        )
        self._track.grid(row=0, column=1, sticky="ew", padx=(0, SPACE_SM))
        # Prevent the track from collapsing vertically.
        self._track.grid_propagate(False)
        self._track.configure(height=bar_height)

        fill_pct = TIER_FILL_PCT.get(tier, 0.5)
        fill_color = _resolve_tier_color(theme, tier)
        # The fill is a sub-frame anchored to the left of the track.
        # Width is set as a percentage of the track's available width.
        # We use a fixed-width initial size + resize on <Configure>.
        self._fill = ctk.CTkFrame(
            self._track, fg_color=fill_color,
            corner_radius=2,
        )
        self._fill.place(x=0, rely=0.0, relheight=1.0, relwidth=fill_pct)

        # Column 2: voice phrase (italic).
        self._voice_label = ctk.CTkLabel(
            self, text=voice_phrase,
            font=(theme.fonts.descriptor[0],
                  theme.fonts.descriptor[1], "italic"),
            text_color=theme.colors.text_primary,
            anchor="w", width=voice_width,
        )
        self._voice_label.grid(row=0, column=2, sticky="w")

        self.grid_columnconfigure(1, weight=1)

        # Tooltip: long phrase on hover.
        tooltip_text = self._long_phrase or voice_phrase
        if tooltip_text:
            try:
                self._tooltip = HoverTooltip(self, text=tooltip_text)
            except Exception:
                self._tooltip = None
        else:
            self._tooltip = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_tier(self, tier, voice_phrase=None, long_phrase=None):
        """Update the tier (+ optionally the voice phrases)."""
        self._tier = tier
        theme = get_theme()
        fill_pct = TIER_FILL_PCT.get(tier, 0.5)
        fill_color = _resolve_tier_color(theme, tier)
        try:
            self._fill.configure(fg_color=fill_color)
            self._fill.place(relwidth=fill_pct)
        except Exception:
            pass
        if voice_phrase is not None:
            self._voice_phrase = voice_phrase
            try:
                self._voice_label.configure(text=voice_phrase)
            except Exception:
                pass
        if long_phrase is not None:
            self._long_phrase = long_phrase
        if self._tooltip is not None:
            self._tooltip.set_text(self._long_phrase or self._voice_phrase)

    def set_label(self, label):
        """Update the attribute label text."""
        self._label_text = label
        try:
            self._label.configure(text=label)
        except Exception:
            pass
