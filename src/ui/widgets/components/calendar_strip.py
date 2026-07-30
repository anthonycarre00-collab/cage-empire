"""CAGE EMPIRE — Phase 2 Component Library: CalendarStrip (§5.12).

Horizontal scrollable strip of dates for the Schedule screen.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.12):

  ┌────────────────────────────────────────────────────────────────────┐
  │ ◀  Mon 14    Tue 15    Wed 16   ●Thu 17   Fri 18   ...          ▶ │
  │     Sep      Sep      Sep      Sep       Sep                      │
  │                                          ▲ NEXT EVENT             │
  └────────────────────────────────────────────────────────────────────┘

  - Container: Card / Flat, 12-col, 64px tall
  - Date cell (resting): 60×48, transparent bg, day-of-week caption
    (uppercase), date mono 14px
  - Date cell (today): gold_tint bg, gold left border 2px
  - Date cell (selected): bg_card_elevated, gold left border 3px
  - Date cell (has event): small gold dot (6×6) below the date number
  - Date cell (next event): gold ▲ marker + "NEXT EVENT" caption
  - Left/right scroll arrows: ghost buttons at the edges

States:
  Hover → gold_tint bg. Click → selected state + shows events for that
  date below.

When to use:
  Schedule screen (primary), Past Events calendar tab, Event Builder
  date picker (modal variant).

CONVENTIONS compliance:
  §14 — Voice Layer: dates are identity strings, not attribute values.
        Day names + month abbreviations are not raw numbers per §14.
"""

from __future__ import annotations

import customtkinter as ctk
from datetime import date, timedelta

from ui.theme import get_theme, tint_to_solid, SPACE_SM, SPACE_MD


class CalendarStrip(ctk.CTkFrame):
    """Horizontal scrollable date strip.

    Args:
        parent: parent widget.
        start_date: datetime.date — the first date in the strip.
            Defaults to today.
        num_days: int — number of date cells. Default 14 (2 weeks).
        selected_date: datetime.date — initially selected date.
            Defaults to start_date.
        today: datetime.date — used to mark the "today" cell.
            Defaults to date.today().
        event_dates: set of datetime.date — dates with events.
            Each gets a gold dot.
        next_event_date: datetime.date — the next upcoming event.
            Gets a gold ▲ marker + "NEXT EVENT" caption.
        on_select: callable(date) — fired when a date is clicked.
        **kwargs: forwarded to CTkFrame.

    Layout: a horizontal CTkScrollableFrame with 60×48 date cells,
    flanked by left/right scroll arrows.
    """

    CELL_W = 60
    CELL_H = 48

    def __init__(self, parent, start_date=None, num_days=14,
                 selected_date=None, today=None, event_dates=None,
                 next_event_date=None, on_select=None, **kwargs):
        super().__init__(parent, fg_color="transparent", corner_radius=0,
                         **kwargs)
        self._start_date = start_date or date.today()
        self._num_days = num_days
        self._today = today or date.today()
        self._selected = selected_date or self._start_date
        self._event_dates = set(event_dates) if event_dates else set()
        self._next_event_date = next_event_date
        self._on_select = on_select
        self._cell_widgets = {}  # date → (frame, day_label, date_label)

        self._build()

    def _build(self):
        theme = get_theme()
        c = theme.colors

        # Left arrow.
        left_arrow = ctk.CTkLabel(
            self, text="◀", font=theme.fonts.body_small,
            text_color=c.text_secondary, cursor="hand2",
            padx=SPACE_SM,
        )
        left_arrow.pack(side="left", padx=(0, SPACE_SM))
        try:
            left_arrow.bind("<Button-1>", lambda e: self._scroll_left(),
                            add="+")
        except Exception:
            pass

        # Scrollable strip.
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", orientation="horizontal",
            height=self.CELL_H + 12,
        )
        self._scroll.pack(side="left", fill="x", expand=True)

        for i in range(self._num_days):
            d = self._start_date + timedelta(days=i)
            cell = self._build_cell(self._scroll, d)
            cell.pack(side="left", padx=(0, SPACE_SM))

        # Right arrow.
        right_arrow = ctk.CTkLabel(
            self, text="▶", font=theme.fonts.body_small,
            text_color=c.text_secondary, cursor="hand2",
            padx=SPACE_SM,
        )
        right_arrow.pack(side="left", padx=(SPACE_SM, 0))
        try:
            right_arrow.bind("<Button-1>", lambda e: self._scroll_right(),
                             add="+")
        except Exception:
            pass

        self._apply_states()

    def _build_cell(self, parent, d):
        """Build one date cell."""
        theme = get_theme()
        c = theme.colors
        cell = ctk.CTkFrame(
            parent, fg_color="transparent", corner_radius=4,
            width=self.CELL_W, height=self.CELL_H,
        )
        try:
            cell.pack_propagate(False)
        except Exception:
            pass

        day_label = ctk.CTkLabel(
            cell, text=d.strftime("%a").upper(),
            font=theme.fonts.caption, text_color=c.text_tertiary,
            anchor="center",
        )
        day_label.pack(anchor="center", pady=(6, 0))

        date_label = ctk.CTkLabel(
            cell, text=str(d.day), font=theme.fonts.mono,
            text_color=c.text_primary, anchor="center",
        )
        date_label.pack(anchor="center")

        # Event dot (hidden by default — shown by _apply_states).
        dot = ctk.CTkFrame(cell, fg_color=c.gold, corner_radius=3,
                           width=6, height=6)
        # Pack only if needed (controlled by _apply_states).

        # Next-event marker.
        next_label = ctk.CTkLabel(
            cell, text="▲ NEXT", font=theme.fonts.caption,
            text_color=c.gold, anchor="center",
        )

        self._cell_widgets[d] = (cell, day_label, date_label, dot, next_label)

        try:
            cell.bind("<Button-1>", lambda e, dd=d: self._on_cell_click(dd),
                      add="+")
            day_label.bind("<Button-1>",
                           lambda e, dd=d: self._on_cell_click(dd),
                           add="+")
            date_label.bind("<Button-1>",
                            lambda e, dd=d: self._on_cell_click(dd),
                            add="+")
        except Exception:
            pass

        return cell

    def _apply_states(self):
        """Apply today/selected/event/next-event styling per cell."""
        theme = get_theme()
        c = theme.colors
        for d, (cell, day_lbl, date_lbl, dot, next_lbl) in self._cell_widgets.items():
            is_today = (d == self._today)
            is_selected = (d == self._selected)
            has_event = (d in self._event_dates)
            is_next = (d == self._next_event_date)

            # Reset.
            try:
                for child in cell.winfo_children():
                    if child is dot or child is next_lbl:
                        child.place_forget()
            except Exception:
                pass

            if is_selected:
                fg = c.bg_card_elevated
                border_color = c.gold
                border_w = 3 if is_today else 2
            elif is_today:
                fg = tint_to_solid(c.gold_tint, c.bg_card_elevated)
                border_color = c.gold
                border_w = 2
            else:
                fg = "transparent"
                border_color = c.border_subtle
                border_w = 0

            try:
                cell.configure(fg_color=fg, border_color=border_color,
                               border_width=border_w)
            except Exception:
                pass

            if has_event and not is_next:
                dot.place(relx=0.5, rely=0.95, anchor="s")
            if is_next:
                next_lbl.place(relx=0.5, rely=1.0, anchor="s",
                               y=-12)

    # ------------------------------------------------------------
    # EVENT HANDLERS
    # ------------------------------------------------------------

    def _on_cell_click(self, d):
        self._selected = d
        self._apply_states()
        if self._on_select is not None:
            try:
                self._on_select(d)
            except Exception as e:
                print(f"[CalendarStrip] on_select failed: {e}", flush=True)

    def _scroll_left(self):
        try:
            self._scroll._parent_canvas.xview_scroll(-3, "units")
        except Exception:
            pass

    def _scroll_right(self):
        try:
            self._scroll._parent_canvas.xview_scroll(3, "units")
        except Exception:
            pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_selected(self, d):
        self._selected = d
        self._apply_states()

    def set_event_dates(self, dates):
        self._event_dates = set(dates) if dates else set()
        self._apply_states()

    def set_next_event(self, d):
        self._next_event_date = d
        self._apply_states()
