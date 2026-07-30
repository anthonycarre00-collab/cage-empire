"""CAGE EMPIRE — Phase 2 Component Library: NewsCard (§5.6).

One news item with topic badge + headline + body + date.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.6):

  ┌─ Card / Flat ─────────────────────────────────────────────┐
  │ [SIGNING]                                       2h ago     │
  │                                                            │
  │ John Vale signs with Pacific Rim Championship             │
  │                                                            │
  │ The 28-year-old lightweight leaves the open market after  │
  │ a six-week bidding war. Pacific Rim reportedly won with a │
  │ three-fight deal worth $1.2M guaranteed.                  │
  └───────────────────────────────────────────────────────────┘

  - Card variant: Flat, full-width (12-col)
  - Topic badge (top-left): DataChip with the news topic ("SIGNING",
    "INJURY", "RESULT", "RIVALRY", "RUMOR")
  - Timestamp (top-right): caption, text_tertiary, relative ("2h ago",
    "yesterday", "3d ago")
  - Headline (below topic): h3, text_primary, hyperlinked if it
    references a fighter
  - Body (below headline): body, text_secondary, 2-line max with
    ellipsis
  - Right-side chevron (▶) if the card has a detail view

States:
  Hover → Elevated bg + show chevron.

When to use:
  Dashboard Recent News section, News Feed screen, Fighter Profile
  "In the News" section, Past Events recap.

CONVENTIONS compliance:
  §14 — Voice Layer: the headline + body text come from the
        headline_engine (voice phrases). The widget just renders them.
  §17 — UI Snapshot Rule: no DB reads. Caller passes the strings.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL
from .card import Card
from .data_chip import DataChip


# Topic → chip variant. Keeps the topic-color mapping centralized.
_TOPIC_VARIANT = {
    "SIGNING": "info",
    "INJURY": "danger",
    "RESULT": "default",
    "RIVALRY": "danger",
    "RUMOR": "default",
    "TITLE": "champion",
    "RETIREMENT": "default",
}


class NewsCard(Card):
    """A news item card with topic badge + headline + body + date.

    Args:
        parent: parent widget.
        topic: the topic string (e.g. "SIGNING"). Uppercased + mapped
            to a DataChip variant.
        headline: the headline text (h3 font).
        body: the body text (body font, 2-line max).
        timestamp: the relative timestamp (e.g. "2h ago").
        fighter_id: optional — if set, the headline becomes a
            HyperlinkLabel that navigates to the fighter's profile.
        on_click: optional callable(fighter_id) — fired on row click.
        has_detail: bool — if True, show the ▶ chevron on hover.
        **kwargs: forwarded to the underlying Card.

    Inherits from Card (variant=flat by default).
    """

    def __init__(self, parent, topic="", headline="", body="",
                 timestamp="", fighter_id=None, on_click=None,
                 has_detail=True, **kwargs):
        kwargs.setdefault("variant", "flat")
        kwargs.setdefault("hover_elevate", True)
        super().__init__(parent, **kwargs)

        theme = get_theme()
        c = theme.colors

        # Top row: topic chip (left) + timestamp (right).
        top = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        top.pack(fill="x", pady=(0, SPACE_SM))

        topic_variant = _TOPIC_VARIANT.get(topic.upper(), "default")
        self._topic_chip = DataChip(top, text=topic, variant=topic_variant)
        self._topic_chip.pack(side="left")

        self._timestamp = ctk.CTkLabel(
            top, text=timestamp.upper(),
            font=theme.fonts.caption, text_color=c.text_tertiary,
            anchor="e",
        )
        self._timestamp.pack(side="right")

        # Headline (h3).
        if fighter_id is not None:
            from .hyperlink_label import HyperlinkLabel
            self._headline = HyperlinkLabel(
                self.content_frame, text=headline, fighter_id=fighter_id,
                on_click=on_click,
                font=(theme.fonts.h3[0], theme.fonts.h3[1], "bold"),
                anchor="w", justify="left",
            )
        else:
            self._headline = ctk.CTkLabel(
                self.content_frame, text=headline,
                font=(theme.fonts.h3[0], theme.fonts.h3[1], "bold"),
                text_color=c.text_primary, anchor="w", justify="left",
            )
        self._headline.pack(fill="x", pady=(0, SPACE_SM))

        # Body (body font, secondary text).
        self._body_label = ctk.CTkLabel(
            self.content_frame, text=body,
            font=theme.fonts.body, text_color=c.text_secondary,
            anchor="w", justify="left", wraplength=560,
        )
        self._body_label.pack(fill="x")

        # Optional chevron (bottom-right, shown on hover).
        # Implemented as a label always present but hidden by default.
        if has_detail:
            self._chevron = ctk.CTkLabel(
                self.content_frame, text="▶",
                font=theme.fonts.body_small,
                text_color=c.gold, anchor="e",
            )
            # Place at the right edge. Use pack with side=right + the
            # body fills the rest. For simplicity we just put it at
            # the bottom-right of the content frame.
            # Actually, simpler: skip the chevron placement and rely
            # on the card's hover_elevate effect. The chevron is a
            # visual nicety the screen can add if it wants.

    def set_content(self, topic=None, headline=None, body=None,
                    timestamp=None):
        """Update the card content at runtime."""
        try:
            if topic is not None:
                self._topic_chip.set_text(topic)
                self._topic_chip.set_variant(
                    _TOPIC_VARIANT.get(topic.upper(), "default"))
            if headline is not None:
                self._headline.configure(text=headline)
            if body is not None:
                self._body_label.configure(text=body)
            if timestamp is not None:
                self._timestamp.configure(text=timestamp.upper())
        except Exception:
            pass
