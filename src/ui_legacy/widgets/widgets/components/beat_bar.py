"""CAGE EMPIRE — Phase 2 Component Library: BeatBar (§5.23).

Fight Night round/clock progress bar with pulse animation.

Props:
  - current_round (int)
  - total_rounds (int)
  - clock_seconds (float, seconds remaining in current round)
  - total_round_seconds (int, default 300 = 5min round)

Renders a horizontal bar split into `total_rounds` segments. Filled
segments = gold, current segment = partially filled gold (proportional
to clock), future segments = border_subtle.

Pulse animation: the current segment's leading edge pulses (opacity
80% → 100% → 80%) every 1s.

Round label: "R2 of 5" (display_small). Clock label: "3:42" (mono).

Use cases:
  - Fight Night screen transport bar (Phase 7)

CONVENTIONS compliance:
  §14 — Voice Layer: round + clock are gameplay-state values, not
        fighter attribute values. Per §14 these are allowed in
        player-facing UI (they're the "game clock" identity, not a
        fighter rating).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD


_PULSE_INTERVAL_MS = 1000  # 1s pulse cycle


class BeatBar(ctk.CTkFrame):
    """A Fight Night round/clock progress bar with pulse animation.

    Args:
        parent: parent widget.
        current_round: int — the round currently in progress (1-indexed).
        total_rounds: int — total rounds in the fight (e.g. 3 or 5).
        clock_seconds: float — seconds remaining in the current round.
        total_round_seconds: int — total seconds per round. Default 300
            (5 minutes × 60).
        animate: if True (default), pulse the current segment's leading
            edge every 1s.
        **kwargs: forwarded to CTkFrame.

    Layout (vertical pack):
      [round label + clock label row]
      [segments row]
    """

    def __init__(self, parent, current_round=1, total_rounds=5,
                 clock_seconds=300.0, total_round_seconds=300,
                 animate=True, **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, **kwargs)
        self._current_round = max(1, int(current_round))
        self._total_rounds = max(1, int(total_rounds))
        self._clock_seconds = max(0.0, float(clock_seconds))
        self._total_round_seconds = max(1, int(total_round_seconds))
        self._animate = animate
        self._pulse_after_id = None
        self._pulse_state = 0  # 0=dim, 1=bright

        self._build()

    def _build(self):
        theme = get_theme()
        c = theme.colors

        # Top row: round label (left) + clock label (right).
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, SPACE_SM))

        self._round_label = ctk.CTkLabel(
            top, text=f"R{self._current_round} of {self._total_rounds}",
            font=theme.fonts.display_small, text_color=c.text_primary,
            anchor="w",
        )
        self._round_label.pack(side="left")

        # Format clock as M:SS.
        mins = int(self._clock_seconds) // 60
        secs = int(self._clock_seconds) % 60
        self._clock_label = ctk.CTkLabel(
            top, text=f"{mins}:{secs:02d}",
            font=theme.fonts.mono, text_color=c.gold,
            anchor="e",
        )
        self._clock_label.pack(side="right")

        # Segments row.
        seg_row = ctk.CTkFrame(self, fg_color="transparent")
        seg_row.pack(fill="x")
        self._segments = []
        for i in range(self._total_rounds):
            seg = ctk.CTkFrame(
                seg_row, fg_color=c.border_subtle,
                corner_radius=2, height=10,
            )
            seg.pack(side="left", fill="x", expand=True,
                     padx=(0 if i == 0 else SPACE_SM // 2,
                           0 if i == self._total_rounds - 1 else SPACE_SM // 2))
            self._segments.append(seg)

        self._apply_segment_fills()

        if self._animate:
            try:
                self.after(800, self._pulse_step)
            except Exception:
                pass

    def _apply_segment_fills(self):
        """Color each segment based on round + clock state."""
        theme = get_theme()
        c = theme.colors
        # Compute the progress within the current round.
        elapsed = max(0, self._total_round_seconds - self._clock_seconds)
        round_progress = max(0.0, min(1.0,
            elapsed / self._total_round_seconds))

        for i, seg in enumerate(self._segments):
            round_num = i + 1  # 1-indexed
            if round_num < self._current_round:
                # Past round — fully filled.
                seg.configure(fg_color=c.gold)
            elif round_num == self._current_round:
                # Current round — proportional fill.
                # We use a sub-frame for the fill.
                self._set_partial_fill(seg, round_progress, c.gold,
                                       c.border_subtle)
            else:
                # Future round — empty (border_subtle track).
                seg.configure(fg_color=c.border_subtle)
                # Remove any partial-fill children from a previous render.
                for child in seg.winfo_children():
                    try:
                        child.destroy()
                    except Exception:
                        pass

    def _set_partial_fill(self, seg, fraction, fill_color, track_color):
        """Fill a segment proportionally to `fraction`."""
        # Destroy existing children.
        for child in seg.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        seg.configure(fg_color=track_color)
        if fraction <= 0:
            return
        fill = ctk.CTkFrame(seg, fg_color=fill_color, corner_radius=2)
        fill.place(x=0, rely=0.0, relheight=1.0, relwidth=fraction)
        # Tag for pulse animation.
        self._current_fill = fill

    def _pulse_step(self):
        """One step of the pulse animation (every 1s)."""
        if not self._animate:
            return
        # Toggle the current fill's opacity by adjusting its color
        # toward gold_bright (bright) / gold (dim).
        try:
            theme = get_theme()
            c = theme.colors
            if hasattr(self, "_current_fill"):
                target = c.gold_bright if self._pulse_state == 0 else c.gold
                self._current_fill.configure(fg_color=target)
            self._pulse_state = 1 - self._pulse_state
        except Exception:
            pass
        try:
            self._pulse_after_id = self.after(_PULSE_INTERVAL_MS,
                                              self._pulse_step)
        except Exception:
            self._pulse_after_id = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_state(self, current_round=None, total_rounds=None,
                  clock_seconds=None, total_round_seconds=None):
        """Update the bar state + re-render."""
        if current_round is not None:
            self._current_round = max(1, int(current_round))
        if total_rounds is not None:
            self._total_rounds = max(1, int(total_rounds))
        if clock_seconds is not None:
            self._clock_seconds = max(0.0, float(clock_seconds))
        if total_round_seconds is not None:
            self._total_round_seconds = max(1, int(total_round_seconds))
        # Re-build (simplest approach — the bar is small).
        for child in self.winfo_children():
            child.destroy()
        self._segments = []
        self._build()

    def destroy(self):
        """Clean up the pulse callback."""
        if self._pulse_after_id is not None:
            try:
                self.after_cancel(self._pulse_after_id)
            except Exception:
                pass
            self._pulse_after_id = None
        super().destroy()
