"""CAGE EMPIRE — Phase 2 Component Library: AttributeBar (§5.20).

Animated fill + voice phrase tooltip + tier color coding.

Props:
  - label (str, e.g. "Striking Power")
  - tier (one of: abysmal, poor, below_avg, avg, above_avg, good,
    elite, exceptional)
  - voice_phrase (str, the descriptor)
  - value (int 0-100, OPTIONAL — only used for bar fill width, NEVER
    displayed as a number per §14)

Bar fill width: tier-based (abysmal=8%, poor=22%, below_avg=36%,
avg=50%, above_avg=64%, good=78%, elite=92%, exceptional=100%).

Bar fill color: crimson for abysmal/poor, steel for below_avg/avg,
gold for above_avg/good/elite, champion_gold for exceptional.

Animation: on first render, bar fills from 0% to target width over
400ms (16ms steps = 60fps).

Hover tooltip: shows the LONG voice phrase (per the interpretation
audit's proposed system).

Layout:
  Label (left, 140px, body_small)
  Bar (center, 8px tall, animated fill)
  Voice phrase (right, 200px, descriptor_small italic)

Use cases:
  - Fighter Profile attribute grid (26 bars)
  - Personality grid (20 bars)
  - Scouting Report projected attributes

CONVENTIONS compliance:
  §14 — Voice Layer: NO raw attribute numbers in player-facing UI.
        AttributeBar's `value` param is for bar fill width ONLY —
        never displayed. The player sees the `voice_phrase` + the
        tier-based fill width. The tooltip shows the LONG voice
        phrase.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM
from ._tooltip import HoverTooltip
from .stat_bar import TIER_FILL_PCT, _resolve_tier_color


_ANIM_STEPS = 25        # 400ms / 16ms = 25 steps
_ANIM_INTERVAL_MS = 16  # ~60fps


class AttributeBar(ctk.CTkFrame):
    """An animated, voice-encoded attribute bar.

    Args:
        parent: parent widget.
        label: the attribute name (e.g. "Striking Power").
        tier: one of abysmal/poor/below_avg/avg/above_avg/good/elite/
            exceptional. Determines fill width + color.
        voice_phrase: the SHORT voice descriptor shown next to the bar.
        long_phrase: optional LONG descriptor shown in the hover
            tooltip. If None, the tooltip shows the short phrase.
        value: optional int 0-100 — overrides the tier-based fill
            width if provided. Used for fine-grained control (rare —
            the spec says fill is tier-based). NEVER DISPLAYED as a
            number per §14.
        animate: if True (default), animate the fill from 0% to
            target on first render. Set False for static contexts
            (e.g., when many bars are rendered simultaneously and
            animation would be distracting).
        label_width: left label column width. Default 140.
        voice_width: right voice-phrase column width. Default 200.
        bar_height: bar fill height. Default 8.
        **kwargs: forwarded to CTkFrame.

    Layout (grid, 3 columns):
      [label | bar track + fill | voice phrase]
    """

    def __init__(self, parent, label="", tier="avg", voice_phrase="",
                 long_phrase=None, value=None, animate=True,
                 label_width=140, voice_width=200, bar_height=8,
                 **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, **kwargs)
        self._label_text = label
        self._tier = tier
        self._voice_phrase = voice_phrase
        self._long_phrase = long_phrase or voice_phrase
        self._value = value
        self._animate = animate
        self._label_width = label_width
        self._voice_width = voice_width
        self._bar_height = bar_height
        self._anim_after_id = None
        self._current_pct = 0.0
        self._target_pct = self._compute_target_pct()

        self._build()
        if animate:
            # Defer the animation start until the widget is mapped
            # (so we know the track width). Use after(50) as a safety.
            try:
                self.after(50, self._start_animation)
            except Exception:
                # If after() fails (e.g., no mainloop in tests), just
                # jump to target.
                self._set_fill_pct(self._target_pct)
        else:
            self._set_fill_pct(self._target_pct)

    def _compute_target_pct(self):
        """Compute the target fill percentage from tier or value."""
        if self._value is not None:
            try:
                return max(0.0, min(1.0, float(self._value) / 100.0))
            except (TypeError, ValueError):
                pass
        return TIER_FILL_PCT.get(self._tier, 0.5)

    def _build(self):
        theme = get_theme()
        c = theme.colors

        # Column 0: label.
        self._label = ctk.CTkLabel(
            self, text=self._label_text,
            font=theme.fonts.body_small, text_color=c.text_secondary,
            anchor="w", width=self._label_width,
        )
        self._label.grid(row=0, column=0, sticky="w", padx=(0, SPACE_SM))

        # Column 1: track + fill.
        self._track = ctk.CTkFrame(
            self, fg_color=c.bg_card_elevated,
            corner_radius=2, height=self._bar_height,
        )
        self._track.grid(row=0, column=1, sticky="ew", padx=(0, SPACE_SM))
        self._track.grid_propagate(False)
        self._track.configure(height=self._bar_height)

        fill_color = _resolve_tier_color(theme, self._tier)
        self._fill = ctk.CTkFrame(
            self._track, fg_color=fill_color, corner_radius=2,
        )
        # Initial position: 0% (animation will grow it).
        self._fill.place(x=0, rely=0.0, relheight=1.0, relwidth=0.0)

        # Column 2: voice phrase.
        self._voice_label = ctk.CTkLabel(
            self, text=self._voice_phrase,
            font=(theme.fonts.descriptor[0],
                  theme.fonts.descriptor[1], "italic"),
            text_color=c.text_primary, anchor="w", width=self._voice_width,
        )
        self._voice_label.grid(row=0, column=2, sticky="w")

        self.grid_columnconfigure(1, weight=1)

        # Tooltip: long phrase on hover.
        tooltip_text = self._long_phrase or self._voice_phrase
        if tooltip_text:
            try:
                self._tooltip = HoverTooltip(self, text=tooltip_text)
            except Exception:
                self._tooltip = None
        else:
            self._tooltip = None

    def _set_fill_pct(self, pct):
        """Set the fill width as a fraction (0.0-1.0)."""
        self._current_pct = max(0.0, min(1.0, pct))
        try:
            self._fill.place(relwidth=self._current_pct)
        except Exception:
            pass

    def _start_animation(self):
        """Kick off the fill animation."""
        if self._anim_after_id is not None:
            try:
                self.after_cancel(self._anim_after_id)
            except Exception:
                pass
        self._animate_step(0)

    def _animate_step(self, step_idx):
        """One step of the fill animation."""
        if step_idx >= _ANIM_STEPS:
            self._set_fill_pct(self._target_pct)
            self._anim_after_id = None
            return
        # Easing: linear (could swap to ease-out cubic for snappier
        # finish, but linear reads as a smooth grow).
        t = (step_idx + 1) / _ANIM_STEPS
        # Slight ease-out: t = 1 - (1-t)^2.
        t_eased = 1 - (1 - t) ** 2
        pct = self._target_pct * t_eased
        self._set_fill_pct(pct)
        try:
            self._anim_after_id = self.after(
                _ANIM_INTERVAL_MS,
                lambda: self._animate_step(step_idx + 1),
            )
        except Exception:
            # No mainloop — jump to target.
            self._set_fill_pct(self._target_pct)
            self._anim_after_id = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_tier(self, tier, voice_phrase=None, long_phrase=None,
                 animate=None):
        """Update the tier + optionally re-animate."""
        self._tier = tier
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
        # Update fill color.
        theme = get_theme()
        fill_color = _resolve_tier_color(theme, tier)
        try:
            self._fill.configure(fg_color=fill_color)
        except Exception:
            pass
        # Re-animate if requested.
        self._target_pct = self._compute_target_pct()
        if animate is None:
            animate = self._animate
        if animate:
            self._current_pct = 0.0
            self._start_animation()
        else:
            self._set_fill_pct(self._target_pct)

    def set_label(self, label):
        self._label_text = label
        try:
            self._label.configure(text=label)
        except Exception:
            pass

    def destroy(self):
        """Clean up the animation callback + tooltip on destroy."""
        if self._anim_after_id is not None:
            try:
                self.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None
        if self._tooltip is not None:
            try:
                self._tooltip.unbind()
            except Exception:
                pass
        super().destroy()
