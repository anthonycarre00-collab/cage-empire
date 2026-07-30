"""CAGE EMPIRE — Phase 2 component library: lightweight hover tooltip.

A minimal, theme-aware tooltip that pops near a widget on <Enter> and
hides on <Leave>. Used by AttributeBar (to show the LONG voice phrase
on hover) + StatBar (same pattern) + any other component that wants
hover-revealed detail without crowding the resting layout.

Architecture:
  - A single Toplevel (per tooltip instance) with overrideredirect(True)
    so it has no window chrome.
  - The Toplevel holds a single CTkLabel with the tooltip text.
  - Position: bottom-center of the target widget, offset by 8px down.
    Clamped to screen edges.
  - Show delay: 350ms after <Enter>. Hide immediately on <Leave>.
  - Text + bg colors read from get_theme() at show time so theme
    switches don't leave tooltips with stale colors.

This is a simplified version of the hover-tooltip pattern used by
HyperlinkLabel — but factored out so multiple components can share
the same behaviour.

CONVENTIONS compliance:
  §14 — Voice Layer: the tooltip text is whatever the caller passes
        (typically the LONG voice phrase for an attribute). No raw
        numbers — the caller is responsible for providing voice.
  §17 — UI Snapshot Rule: no DB reads. Pure UI plumbing.
"""

from __future__ import annotations

import customtkinter as ctk
from ui.theme import get_theme


_SHOW_DELAY_MS = 350  # 350ms hover → tooltip appears


class HoverTooltip:
    """A lightweight hover tooltip for a single target widget.

    Args:
        target: the widget to hover on. <Enter> + <Leave> are bound
            here.
        text: the tooltip text. Can be updated via set_text().
        font: optional font tuple. Defaults to caption.
        wraplength: optional wrap width in px. Defaults to 320.
        delay_ms: optional show delay. Defaults to 350ms.

    Lifecycle:
      - Bound on construction.
      - unbind() removes the bindings + destroys the Toplevel.
      - Re-bindable to a new target via rebind(new_target).

    Defensive:
      - All Tk operations wrapped in try/except — a tooltip failure
        must NEVER crash the screen it lives in.
    """

    def __init__(self, target, text="", font=None, wraplength=320,
                 delay_ms=_SHOW_DELAY_MS):
        self._target = target
        self._text = text
        self._font = font
        self._wraplength = wraplength
        self._delay_ms = delay_ms
        self._top = None
        self._after_id = None
        self._bound = False
        self.bind()

    # ------------------------------------------------------------
    # BINDING LIFECYCLE
    # ------------------------------------------------------------

    def bind(self):
        """Bind <Enter> + <Leave> on the target."""
        if self._bound or self._target is None:
            return
        try:
            self._target.bind("<Enter>", self._on_enter, add="+")
            self._target.bind("<Leave>", self._on_leave, add="+")
            self._bound = True
        except Exception:
            self._bound = False

    def unbind(self):
        """Unbind + destroy the tooltip Toplevel."""
        try:
            if self._after_id is not None:
                self._target.after_cancel(self._after_id)
                self._after_id = None
        except Exception:
            pass
        if self._bound and self._target is not None:
            try:
                self._target.unbind("<Enter>")
                self._target.unbind("<Leave>")
            except Exception:
                pass
            self._bound = False
        self._hide_now()

    def rebind(self, new_target):
        """Move the tooltip to a new target widget."""
        self.unbind()
        self._target = new_target
        self.bind()

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_text(self, text):
        """Update the tooltip text. If currently shown, refreshes."""
        self._text = text
        if self._top is not None:
            try:
                self._top_label.configure(text=text)
            except Exception:
                pass

    # ------------------------------------------------------------
    # EVENT HANDLERS
    # ------------------------------------------------------------

    def _on_enter(self, event=None):
        """<Enter> handler — schedule the show after delay_ms."""
        if self._after_id is not None:
            try:
                self._target.after_cancel(self._after_id)
            except Exception:
                pass
        try:
            self._after_id = self._target.after(self._delay_ms, self._show_now)
        except Exception:
            self._after_id = None

    def _on_leave(self, event=None):
        """<Leave> handler — cancel pending show + hide immediately."""
        if self._after_id is not None:
            try:
                self._target.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._hide_now()

    # ------------------------------------------------------------
    # SHOW / HIDE
    # ------------------------------------------------------------

    def _show_now(self):
        """Create + position the tooltip Toplevel."""
        if self._target is None:
            return
        try:
            if self._top is not None:
                # Already shown — refresh colors + text in case of theme switch.
                self._apply_theme_to_top()
                return
            top = ctk.CTkToplevel(self._target)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            # On some platforms, an empty initial geometry prevents the
            # Toplevel from briefly flashing at (0,0).
            top.geometry(f"1x1+-100+-100")

            theme = get_theme()
            font = self._font or theme.fonts.caption
            label = ctk.CTkLabel(
                top, text=self._text, font=font,
                text_color=theme.colors.text_primary,
                fg_color=theme.colors.bg_card_elevated,
                border_color=theme.colors.border_subtle,
                border_width=1, corner_radius=4,
                padx=8, pady=4, wraplength=self._wraplength,
                justify="left", anchor="w",
            )
            label.pack(fill="both", expand=True)
            self._top = top
            self._top_label = label

            # Position: bottom-center of target, 8px below.
            self._target.update_idletasks()
            wx = self._target.winfo_rootx()
            wy = self._target.winfo_rooty()
            ww = self._target.winfo_width()
            wh = self._target.winfo_height()
            # Measure the tooltip.
            top.update_idletasks()
            tw = top.winfo_reqwidth()
            th = top.winfo_reqheight()
            tx = wx + (ww - tw) // 2
            ty = wy + wh + 8
            # Clamp to screen.
            try:
                sw = top.winfo_screenwidth()
                sh = top.winfo_screenheight()
                tx = max(8, min(tx, sw - tw - 8))
                ty = max(8, min(ty, sh - th - 8))
            except Exception:
                pass
            top.geometry(f"{tw}x{th}+{tx}+{ty}")
        except Exception as e:
            # Defensive — tooltip failure shouldn't crash the screen.
            try:
                print(f"[HoverTooltip] show failed: {e}", flush=True)
            except Exception:
                pass

    def _hide_now(self):
        """Destroy the tooltip Toplevel."""
        if self._top is not None:
            try:
                self._top.destroy()
            except Exception:
                pass
            self._top = None
            self._top_label = None

    def _apply_theme_to_top(self):
        """Refresh the tooltip's colors after a theme switch."""
        if self._top is None or self._top_label is None:
            return
        try:
            theme = get_theme()
            self._top_label.configure(
                text=self._text,
                font=self._font or theme.fonts.caption,
                text_color=theme.colors.text_primary,
                fg_color=theme.colors.bg_card_elevated,
                border_color=theme.colors.border_subtle,
            )
        except Exception:
            pass
