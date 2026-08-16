"""CAGE EMPIRE — Phase 2 Component Library: WatchCard (§5.7).

One of the 3 Fighter Watch cards on Dashboard (Top Prospect / Hottest
Streak / Biggest Fall).

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.7):

  ┌─ Card / Accent (gold border for Top Prospect, crimson for
  │                Biggest Fall) ──────────────────────────────────────┐
  │ TOP PROSPECT                                            ▲ +12       │
  │                                                                      │
  │ ┌──────┐                                                             │
  │ │ 64px │   John Vale                                                 │
  │ │ port │   18-5-0 · LW · 28yo                                        │
  │ └──────┘                                                             │
  │                                                                      │
  │ "the wunderkind everyone's talking about"                            │
  │                                                                      │
  │ Signed 6 weeks ago. Three wins in a row. Promoters are circling.     │
  └──────────────────────────────────────────────────────────────────────┘

  - Card variant: Accent (gold border for Top Prospect + Hottest
    Streak, crimson border for Biggest Fall)
  - Section eyebrow (top-left): caption uppercase, gold or crimson
  - Delta indicator (top-right): mono_small, ▲ or ▼ (the trend)
  - Portrait (left, 64×64): PortraitFrame mini variant
  - Name (right of portrait): h3 bold, gold hyperlink
  - Stats line: body_small, text_secondary, mono for record
  - Voice phrase (centered, italicized): descriptor italic
  - Context line (bottom): body_small, text_secondary

States:
  Hover → Elevated bg (the accent border stays). Click → navigates
  to Fighter Profile.

When to use:
  Dashboard Fighter Watch section. Only 3 instances at a time. The
  visual weight is intentional — these are the 3 stories the player
  should care about today.

CONVENTIONS compliance:
  §14 — Voice Layer: voice phrase is the LONG variant (audit doc §3).
        Context line is a 1-sentence summary from
        daily_headlines.body_text (truncated ~80 chars).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM, SPACE_MD, SPACE_LG
from .card import Card
from .portrait_frame import PortraitFrame
from .hyperlink_label import HyperlinkLabel


class WatchCard(Card):
    """A Fighter Watch card (one of 3 on Dashboard).

    Args:
        parent: parent widget.
        eyebrow: the section eyebrow (e.g. "TOP PROSPECT"). Will be
            uppercased.
        delta_text: the delta indicator (e.g. "▲ +12", "▼ -3"). Mono
            font, trend color.
        delta_direction: "up" | "down" | "flat" — controls color
            (gold/crimson/steel).
        fighter_id: the fighter's DB id (used for the hyperlink + the
            portrait click).
        fighter_name: the fighter's name (h3 bold, gold hyperlink).
        stats_line: the stats line (e.g. "18-5-0 · LW · 28yo").
        voice_phrase: the LONG voice phrase, italic, centered.
        context_line: 1-sentence context summary.
        portrait_ctk_image: optional CTkImage for the portrait. If
            None, PortraitFrame shows a placeholder.
        is_champion: bool — gold border (champion variant).
        is_falling: bool — crimson border (Biggest Fall variant).
        on_click: callable(fighter_id) — fired on card click.
        **kwargs: forwarded to Card.

    Inherits from Card (variant=accent).
    """

    def __init__(self, parent, eyebrow="", delta_text="",
                 delta_direction="flat", fighter_id=None,
                 fighter_name="", stats_line="", voice_phrase="",
                 context_line="", portrait_ctk_image=None,
                 is_champion=False, is_falling=False, on_click=None,
                 **kwargs):
        # Resolve accent color: gold for champion + rising, crimson for
        # falling.
        if is_falling:
            accent_color = get_theme().colors.crimson
        else:
            accent_color = get_theme().colors.gold

        kwargs.setdefault("variant", "accent")
        kwargs.setdefault("accent_color", accent_color)
        kwargs.setdefault("hover_elevate", True)
        super().__init__(parent, **kwargs)

        theme = get_theme()
        c = theme.colors

        # Top row: eyebrow (left) + delta (right).
        top = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        top.pack(fill="x", pady=(0, SPACE_MD))

        eyebrow_color = c.crimson if is_falling else c.gold
        self._eyebrow = ctk.CTkLabel(
            top, text=eyebrow.upper(),
            font=theme.fonts.caption, text_color=eyebrow_color,
            anchor="w",
        )
        self._eyebrow.pack(side="left")

        delta_color = (c.gold if delta_direction == "up"
                       else c.crimson if delta_direction == "down"
                       else c.steel)
        self._delta = ctk.CTkLabel(
            top, text=delta_text, font=theme.fonts.mono,
            text_color=delta_color, anchor="e",
        )
        self._delta.pack(side="right")

        # Middle row: portrait (left) + name + stats (right).
        middle = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        middle.pack(fill="x", pady=(0, SPACE_MD))

        self._portrait = PortraitFrame(
            middle, ctk_image=portrait_ctk_image, size="watch",
            is_champion=is_champion, fighter_id=fighter_id,
            on_click=on_click,
        )
        self._portrait.pack(side="left", padx=(0, SPACE_MD))

        right = ctk.CTkFrame(middle, fg_color="transparent")
        right.pack(side="left", fill="x", expand=True)

        if fighter_id is not None:
            self._name_label = HyperlinkLabel(
                right, text=fighter_name, fighter_id=fighter_id,
                on_click=on_click,
                font=(theme.fonts.h3[0], theme.fonts.h3[1], "bold"),
                anchor="w",
            )
        else:
            self._name_label = ctk.CTkLabel(
                right, text=fighter_name,
                font=(theme.fonts.h3[0], theme.fonts.h3[1], "bold"),
                text_color=c.text_primary, anchor="w",
            )
        self._name_label.pack(anchor="w")

        self._stats_label = ctk.CTkLabel(
            right, text=stats_line, font=theme.fonts.body_small,
            text_color=c.text_secondary, anchor="w",
        )
        self._stats_label.pack(anchor="w", pady=(SPACE_SM, 0))

        # Voice phrase (italic, centered).
        self._voice_label = ctk.CTkLabel(
            self.content_frame, text=voice_phrase,
            font=(theme.fonts.descriptor[0],
                  theme.fonts.descriptor[1], "italic"),
            text_color=c.text_primary, anchor="center",
            justify="center", wraplength=320,
        )
        self._voice_label.pack(fill="x", pady=(0, SPACE_SM))

        # Context line (bottom).
        self._context_label = ctk.CTkLabel(
            self.content_frame, text=context_line,
            font=theme.fonts.body_small, text_color=c.text_secondary,
            anchor="w", justify="left", wraplength=320,
        )
        self._context_label.pack(fill="x")

        # Click binding on the whole card (in addition to the
        # hyperlink + portrait, which navigate on their own).
        if on_click is not None and fighter_id is not None:
            try:
                self.bind("<Button-1>",
                          lambda e: self._fire_on_click(on_click, fighter_id),
                          add="+")
            except Exception:
                pass

    def _fire_on_click(self, on_click, fighter_id):
        try:
            on_click(fighter_id)
        except Exception as e:
            print(f"[WatchCard] on_click failed: {e}", flush=True)
