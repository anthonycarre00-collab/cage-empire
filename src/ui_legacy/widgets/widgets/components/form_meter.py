"""CAGE EMPIRE — Phase 2 Component Library: FormMeter (§5.18).

Visual win/loss streak bar.

Props:
  - results: list of 'W'/'L'/'D' for last 5-10 fights
  - orientation: 'horizontal' default

Renders a row of 5-10 colored blocks: gold for W, crimson for L, steel
for D. Each block 24×24, 2px gap.

Optional: a thin sparkline below showing the fighter's "form score"
over time.

Use cases:
  - Fighter Profile recent fights summary
  - Roster table "Form" column (compact variant)
  - Dashboard Watch Cards

CONVENTIONS compliance:
  §14 — Voice Layer: W/L/D are result codes (career stats, allowed
        per §14). The meter itself is a visualization, not text. The
        optional form-score sparkline is also a visualization.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_XS, SPACE_SM, tint_to_solid
from ._pil_utils import make_ctk_form_block, HAS_PIL
from .sparkline import Sparkline


_BLOCK_SIZE = 24
_BLOCK_GAP = 2


class FormMeter(ctk.CTkFrame):
    """A visual win/loss streak bar.

    Args:
        parent: parent widget.
        results: list of 'W' / 'L' / 'D' (case-insensitive). Maximum
            10 blocks shown (older results beyond 10 are ignored).
        show_form_score: if True, show a thin sparkline below the
            blocks representing the fighter's "form score" over time.
            The form score is computed as +1 per W, -1 per L, 0 per D,
            cumulative.
        compact: if True, blocks are 16×16 instead of 24×24 (for
            table-row contexts). Default False.
        orientation: "horizontal" (default) — only horizontal is
            supported in Phase 2 (vertical was in the spec but no
            screen uses it yet).
        **kwargs: forwarded to CTkFrame.

    Layout (vertical pack):
      [row of blocks]
      [optional form-score sparkline]
    """

    def __init__(self, parent, results=None, show_form_score=False,
                 compact=False, orientation="horizontal", **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, **kwargs)
        self._results = list(results) if results else []
        self._show_form_score = show_form_score
        self._compact = compact
        self._orientation = orientation
        self._block_size = 16 if compact else _BLOCK_SIZE
        self._build()

    def _build(self):
        theme = get_theme()
        c = theme.colors

        # The blocks row.
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="top", anchor="w")

        # Limit to 10 most-recent results.
        recent = self._results[-10:] if self._results else []
        for r in recent:
            code = str(r).strip().upper()
            if code == "W":
                color = c.gold
            elif code == "L":
                color = c.crimson
            elif code == "D":
                color = c.steel
            else:
                # Skip unknown codes silently.
                continue

            if HAS_PIL:
                # PIL block (rounded rect with subtle border).
                img = make_ctk_form_block(
                    size=self._block_size, color=color,
                    border_color=tint_to_solid(c.gold_tint, color)
                    if code == "W" else "rgba(0,0,0,0)",
                    border_width=1 if code == "W" else 0,
                    radius=3,
                )
                if img is not None:
                    block = ctk.CTkLabel(row, image=img, text="",
                                         fg_color="transparent")
                else:
                    # PIL fallback — solid color frame.
                    block = ctk.CTkFrame(row, fg_color=color,
                                         corner_radius=3,
                                         width=self._block_size,
                                         height=self._block_size)
            else:
                block = ctk.CTkFrame(row, fg_color=color,
                                     corner_radius=3,
                                     width=self._block_size,
                                     height=self._block_size)
            block.pack(side="left", padx=(0, _BLOCK_GAP))
            try:
                block.pack_propagate(False)
            except Exception:
                pass

        # Optional form-score sparkline.
        if self._show_form_score and len(self._results) >= 2:
            try:
                score = 0
                scores = []
                for r in self._results:
                    code = str(r).strip().upper()
                    if code == "W":
                        score += 1
                    elif code == "L":
                        score -= 1
                    scores.append(score)
                self._form_spark = Sparkline(
                    self, data=scores, width=120, height=16,
                    line_color=c.gold,
                    fill_color=tint_to_solid(c.gold_tint, c.bg_card_elevated),
                )
                self._form_spark.pack(side="top", anchor="w",
                                      pady=(SPACE_XS, 0))
            except Exception:
                self._form_spark = None
        else:
            self._form_spark = None

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_results(self, results):
        """Update the results + re-render."""
        for child in self.winfo_children():
            child.destroy()
        self._results = list(results) if results else []
        self._build()
