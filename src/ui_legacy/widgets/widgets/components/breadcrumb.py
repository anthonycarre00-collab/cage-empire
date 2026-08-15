"""CAGE EMPIRE — Phase 2 Component Library: Breadcrumb (§5.13).

"Home > Fighters > John Vale" navigation trail.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.13):

  The Stable  /  John Vale

  - Container: transparent bg, 24px tall, sits below the top bar
  - Segment (resting): body_small (Inter 13px), text_secondary
  - Segment (hover): text_primary, gold underline (1px)
  - Separator: " / " in text_tertiary
  - Last segment (current page): text_primary Bold, no hover (not
    clickable)

When to use:
  Fighter Profile (above the H1), Scouting Report detail, Past Events
  event detail, Hall of Fame inductee detail. Anywhere the player has
  drilled 2+ levels deep.

When NOT to use:
  On top-level nav destinations (Dashboard, Roster, Free Agents, etc.)
  — the sidebar already indicates location.

CONVENTIONS compliance:
  §14 — Voice Layer: segments are identity strings (fighter names,
        screen names), not attribute values.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_XS, SPACE_SM


class Breadcrumb(ctk.CTkFrame):
    """A horizontal breadcrumb navigation trail.

    Args:
        parent: parent widget.
        segments: list of (segment_id, label) tuples. The last segment
            is rendered as the current page (not clickable).
        on_navigate: callable(segment_id) — fired when a non-current
            segment is clicked.
        **kwargs: forwarded to CTkFrame.

    Layout: horizontal pack of [segment] [/] [segment] [/] [segment].
    """

    def __init__(self, parent, segments=None, on_navigate=None, **kwargs):
        super().__init__(parent, fg_color="transparent", corner_radius=0,
                         height=24, **kwargs)
        self._segments = list(segments) if segments else []
        self._on_navigate = on_navigate
        self._seg_labels = []
        self._build()

    def _build(self):
        theme = get_theme()
        c = theme.colors

        # Clear any existing children (for re-builds).
        for child in self.winfo_children():
            child.destroy()
        self._seg_labels.clear()

        n = len(self._segments)
        for i, (seg_id, label) in enumerate(self._segments):
            is_last = (i == n - 1)
            font = (theme.fonts.body_small[0],
                    theme.fonts.body_small[1], "bold") if is_last \
                else theme.fonts.body_small
            text_color = c.text_primary if is_last else c.text_secondary

            seg = ctk.CTkLabel(
                self, text=label, font=font, text_color=text_color,
                anchor="w",
            )
            seg.pack(side="left")
            self._seg_labels.append(seg)

            if not is_last:
                # Clickable + hover underline.
                try:
                    seg.configure(cursor="hand2")
                    seg.bind("<Button-1>",
                             lambda e, sid=seg_id: self._on_seg_click(sid),
                             add="+")
                    seg.bind("<Enter>",
                             lambda e, s=seg: self._on_seg_enter(s),
                             add="+")
                    seg.bind("<Leave>",
                             lambda e, s=seg: self._on_seg_leave(s),
                             add="+")
                except Exception:
                    pass

                # Separator.
                sep = ctk.CTkLabel(
                    self, text="/", font=theme.fonts.body_small,
                    text_color=c.text_tertiary, anchor="center",
                    padx=SPACE_XS,
                )
                sep.pack(side="left")

        try:
            self.pack_propagate(False)
        except Exception:
            pass

    def _on_seg_click(self, seg_id):
        if self._on_navigate is not None:
            try:
                self._on_navigate(seg_id)
            except Exception as e:
                print(f"[Breadcrumb] on_navigate failed: {e}", flush=True)

    def _on_seg_enter(self, seg_label):
        try:
            theme = get_theme()
            seg_label.configure(text_color=theme.colors.text_primary)
            # Underline via font tuple with 4th elem True.
            f = seg_label.cget("font")
            if isinstance(f, (tuple, list)) and len(f) < 4:
                seg_label.configure(font=tuple(f) + (True,))
        except Exception:
            pass

    def _on_seg_leave(self, seg_label):
        try:
            theme = get_theme()
            seg_label.configure(text_color=theme.colors.text_secondary)
            f = seg_label.cget("font")
            if isinstance(f, (tuple, list)) and len(f) >= 4:
                seg_label.configure(font=tuple(f[:3]))
        except Exception:
            pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_segments(self, segments):
        self._segments = list(segments) if segments else []
        self._build()
