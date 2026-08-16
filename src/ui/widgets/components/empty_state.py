"""CAGE EMPIRE — Phase 2 Component Library: EmptyState (§5.14).

When no data, show personality, not "No data."

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.14):

  ┌─ Card / Flat ────────────────────────────────────────┐
  │                                                       │
  │                   [48×48 icon, gold]                  │
  │                                                       │
  │              The newswire is quiet.                   │
  │                                                       │
  │       No stories have broken in the last 24 hours.    │
  │       Advance a day to see what develops.             │
  │                                                       │
  │                  [▶ Advance Day]                      │
  │                                                       │
  └───────────────────────────────────────────────────────┘

  - Container: Card / Flat, centered, max 600×400
  - Icon (top-center): 48×48, gold, custom per empty-state type
  - Headline (center): h2 (Inter 18px Bold), text_primary
  - Body (center, max 400px wide): body (Inter 14px), text_secondary
  - CTA (center, optional): Primary Button

Voice/type:
  Each empty state gets a UNIQUE voice phrase per screen. The "No
  data" pattern is banned. Examples:

  | Screen          | Headline                  | Body                                |
  |-----------------|---------------------------|-------------------------------------|
  | Dashboard news  | "The newswire is quiet."  | "No stories have broken in the..."  |
  | Roster          | "Your stable is empty."   | "Sign fighters from the Open..."    |
  | Free Agents     | "The market is quiet."    | "No unsigned fighters match..."     |
  | Fighter Watch   | "No one's making moves."  | "The divisions are resting..."      |
  | Past Events     | "No events yet."          | "Once you run your first card..."   |
  | Hall of Fame    | "No legends yet."         | "Retirees with distinguished..."    |
  | Rivalries       | "No bad blood brewing."   | "Rivalries develop over time..."    |

When to use:
  Every screen that can be empty MUST have an empty state. No blank
  voids.

CONVENTIONS compliance:
  §14 — Voice Layer: the headline + body are voice phrases (caller-
        provided per screen, never generic "No data").
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_2XL
from .card import Card
from .button import Button


class EmptyState(Card):
    """A personality-driven empty-state card.

    Args:
        parent: parent widget.
        headline: the h2 headline (e.g. "The newswire is quiet.").
        body: the body text. Wrapped at 400px.
        icon_text: optional — a single character / emoji rendered as
            the 48×48 gold icon (e.g. "📰", "□"). If None, no icon
            is shown.
        icon_ctk_image: optional CTkImage — used INSTEAD of icon_text
            if provided. Sized at 48×48.
        cta_text: optional — the primary CTA button label.
        cta_on_click: callable() — fired when the CTA is clicked.
        **kwargs: forwarded to Card (default variant=flat).

    The card auto-centers its content. Caller should pack/grid it
    fill="both" expand=True so the card fills available space and the
    content centers within.
    """

    def __init__(self, parent, headline="", body="",
                 icon_text=None, icon_ctk_image=None,
                 cta_text=None, cta_on_click=None, **kwargs):
        kwargs.setdefault("variant", "flat")
        super().__init__(parent, **kwargs)

        theme = get_theme()
        c = theme.colors

        # The content_frame from Card is packed with padding. We add
        # a centering wrapper.
        center = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        center.pack(fill="both", expand=True)
        # Center the children vertically + horizontally via pack anchor.

        # Icon.
        if icon_ctk_image is not None:
            icon = ctk.CTkLabel(center, image=icon_ctk_image, text="",
                                fg_color="transparent")
        elif icon_text:
            icon = ctk.CTkLabel(
                center, text=str(icon_text),
                font=(theme.fonts.display[0], 48, "bold"),
                text_color=c.gold, fg_color="transparent",
            )
        else:
            icon = None
        if icon is not None:
            icon.pack(pady=(SPACE_LG, SPACE_MD))

        # Headline.
        self._headline = ctk.CTkLabel(
            center, text=headline,
            font=theme.fonts.h2, text_color=c.text_primary,
            anchor="center", justify="center", wraplength=400,
        )
        self._headline.pack(pady=(SPACE_MD, SPACE_SM))

        # Body.
        self._body = ctk.CTkLabel(
            center, text=body, font=theme.fonts.body,
            text_color=c.text_secondary, anchor="center",
            justify="center", wraplength=400,
        )
        self._body.pack(pady=(SPACE_SM, SPACE_LG))

        # CTA.
        if cta_text and cta_on_click is not None:
            self._cta = Button(
                center, text=cta_text, variant="primary",
                on_click=cta_on_click,
            )
            self._cta.pack(pady=(SPACE_MD, SPACE_LG))
        else:
            self._cta = None

    def set_content(self, headline=None, body=None, icon_text=None):
        try:
            if headline is not None:
                self._headline.configure(text=headline)
            if body is not None:
                self._body.configure(text=body)
        except Exception:
            pass
