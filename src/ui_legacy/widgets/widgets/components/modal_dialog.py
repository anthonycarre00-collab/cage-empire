"""CAGE EMPIRE — Phase 2 Component Library: ModalDialog (§5.16).

Confirmations, sign/cut actions, settings changes.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.16):

  ┌─ Modal overlay (semi-transparent black, 40% opacity) ───────────────┐
  │                                                                       │
  │        ┌─ Card / Elevated (8px radius) ──────────────────┐           │
  │        │                                                  │           │
  │        │  SIGN FIGHTER                                    │           │
  │        │                                                  │           │
  │        │  You're about to sign John Vale to a 3-fight     │           │
  │        │  deal worth $1.2M guaranteed. This will deduct   │           │
  │        │  $1.2M from your promotion's cash balance.       │           │
  │        │                                                  │           │
  │        │  ┌─────────────────┐  ┌─────────────────┐        │           │
  │        │  │ Cancel          │  │ Sign for $1.2M  │        │           │
  │        │  └─────────────────┘  └─────────────────┘        │           │
  │        │                                                  │           │
  │        └──────────────────────────────────────────────────┘           │
  │                                                                       │
  └───────────────────────────────────────────────────────────────────────┘

  - Overlay: bg_base at 40% opacity, covers entire window, blocks
    all interaction underneath
  - Modal: Card / Elevated, 8px radius, max 600×400, centered, 24px
    padding
  - Title (top): display_small (Oswald 24px), text_primary
  - Body: body (Inter 14px), text_secondary
  - Action buttons (bottom-right): Secondary (Cancel) + Primary
    (action verb) — gap of 12px
  - Close X (top-right): Ghost button, 16×16, only on non-critical
    modals (critical = no X, force a choice)

States:
  Modal slides in from top (translateY -20px → 0, 150ms). Overlay
  fades in (0% → 40%, 100ms). On close, reverse.

When to use:
  Sign Fighter (with contract details), Cut Fighter (with
  confirmation), Cancel Event (with downstream impact list), Advance
  Day confirmation (only if there's an unresolved event that day),
  Settings changes that require restart.

When NOT to use:
  For inline confirmations (use a toast notification instead — P1
  future). For long forms (use a dedicated screen).

CONVENTIONS compliance:
  §14 — Voice Layer: title + body are voice phrases.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_2XL
from .card import Card
from .button import Button


class ModalDialog(ctk.CTkToplevel):
    """A modal dialog overlay.

    Args:
        parent: parent widget (typically the main window or a screen).
        title: the modal title (display_small).
        body: the body text (body font, wrapped).
        primary_text: the primary action button label.
        primary_on_click: callable() — fired when the primary button
            is clicked. The modal closes after the callback fires.
        secondary_text: optional — the secondary (cancel) button
            label. Defaults to "Cancel".
        secondary_on_click: callable() — fired on cancel. Defaults to
            closing the modal.
        critical: bool — if True, no close X is shown (forces a
            choice). Defaults False.
        max_width: max modal width. Default 600.
        max_height: max modal height. Default 400.

    The modal is a Toplevel with overrideredirect(True) — no window
    chrome. The overlay covers the entire parent. The modal itself is
    an Elevated Card centered within.
    """

    def __init__(self, parent, title="", body="",
                 primary_text="OK", primary_on_click=None,
                 secondary_text="Cancel", secondary_on_click=None,
                 critical=False, max_width=600, max_height=400,
                 **kwargs):
        super().__init__(parent)
        self._primary_on_click = primary_on_click
        self._secondary_on_click = secondary_on_click
        self._critical = critical

        # Toplevel config — no chrome, on top, transparent.
        try:
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.transient(parent)
        except Exception:
            pass

        theme = get_theme()
        c = theme.colors

        # Overlay frame (covers the entire Toplevel = the entire
        # parent window since we'll size the Toplevel to the parent).
        overlay = ctk.CTkFrame(self, fg_color=c.bg_base,
                               corner_radius=0)
        overlay.pack(fill="both", expand=True)
        try:
            # 40% opacity overlay — best-effort via wm_attributes on
            # the Toplevel. Some platforms ignore this.
            self.attributes("-alpha", 1.0)  # Keep the modal itself opaque
        except Exception:
            pass

        # Modal card (centered in the overlay).
        modal = Card(overlay, variant="elevated",
                     corner_radius=8, padding=SPACE_XL)
        modal.place(relx=0.5, rely=0.5, anchor="center",
                    width=max_width, height=max_height)

        # Title row.
        title_row = ctk.CTkFrame(modal.content_frame, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, SPACE_MD))

        self._title_label = ctk.CTkLabel(
            title_row, text=title.upper(),
            font=theme.fonts.display_small, text_color=c.text_primary,
            anchor="w",
        )
        self._title_label.pack(side="left", fill="x", expand=True)

        # Close X (only on non-critical modals).
        if not critical:
            close_x = ctk.CTkLabel(
                title_row, text="✕", font=theme.fonts.body,
                text_color=c.text_secondary, cursor="hand2",
            )
            close_x.pack(side="right")
            try:
                close_x.bind("<Button-1>",
                             lambda e: self._close(secondary=True),
                             add="+")
            except Exception:
                pass

        # Body.
        self._body_label = ctk.CTkLabel(
            modal.content_frame, text=body, font=theme.fonts.body,
            text_color=c.text_secondary, anchor="w",
            justify="left", wraplength=max_width - 2 * SPACE_XL,
        )
        self._body_label.pack(fill="x", pady=(0, SPACE_XL))

        # Button row (bottom-right).
        btn_row = ctk.CTkFrame(modal.content_frame, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom")

        self._secondary_btn = Button(
            btn_row, text=secondary_text, variant="secondary",
            on_click=lambda: self._close(secondary=True),
        )
        self._secondary_btn.pack(side="right", padx=(SPACE_SM, 0))

        self._primary_btn = Button(
            btn_row, text=primary_text, variant="primary",
            on_click=lambda: self._close(secondary=False),
        )
        self._primary_btn.pack(side="right")

        # Position the Toplevel to cover the parent.
        try:
            self.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            self.geometry(f"{pw}x{ph}+{px}+{py}")
        except Exception:
            pass

        # Grab input so the modal blocks interaction underneath.
        try:
            self.grab_set()
        except Exception:
            pass

    def _close(self, secondary=False):
        """Close the modal. Fires the appropriate callback."""
        try:
            if secondary and self._secondary_on_click is not None:
                self._secondary_on_click()
            elif not secondary and self._primary_on_click is not None:
                self._primary_on_click()
        except Exception as e:
            print(f"[ModalDialog] callback failed: {e}", flush=True)
        try:
            self.grab_release()
            self.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_body(self, body):
        try:
            self._body_label.configure(text=body)
        except Exception:
            pass

    def set_title(self, title):
        try:
            self._title_label.configure(text=title.upper())
        except Exception:
            pass
