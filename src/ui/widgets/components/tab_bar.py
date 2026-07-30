"""CAGE EMPIRE — Phase 2 Component Library: TabBar (§5.11).

Sub-navigation within a screen (e.g., Fighter Profile:
Overview / Attributes / Personality / Career / Fights / News).

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.11):

  - Container: transparent bg, 1px border_subtle bottom border
  - Tab (resting): body_small (Inter 13px), text_secondary,
    padding 8×16
  - Tab (hover): text_primary, gold_tint bg (subtle)
  - Tab (active): text_primary Bold, 3px gold bottom border (replaces
    the 1px container border for the active tab)
  - Tab (disabled): text_tertiary, cursor = arrow

States: Tabs do NOT have a "selected bg" — the gold bottom border is
the indicator.

When to use:
  Fighter Profile (6 tabs), Finance (3 tabs: Income / Expenses /
  Forecast), Past Events (2 tabs: List / Calendar), Settings (4 tabs:
  Display / Audio / Gameplay / Mods).

CONVENTIONS compliance:
  §14 — Voice Layer: tab labels are voice phrases (caller-provided).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, tint_to_solid, SPACE_MD, SPACE_LG


class TabBar(ctk.CTkFrame):
    """A horizontal sub-navigation tab bar.

    Args:
        parent: parent widget.
        tabs: list of (tab_id, label) tuples. tab_id is the string
            passed to on_change when the tab is clicked.
        active_tab: the initial active tab_id. Defaults to the first.
        on_change: callable(tab_id) — fired when the user clicks a tab.
        **kwargs: forwarded to CTkFrame.

    Layout (grid, single row):
      [tab1 | tab2 | tab3 | ...]
    The active tab has a 3px gold bottom border (drawn via a sub-frame
    at the bottom of the tab cell).
    """

    def __init__(self, parent, tabs=None, active_tab=None, on_change=None,
                 **kwargs):
        super().__init__(parent, fg_color="transparent", corner_radius=0,
                         **kwargs)
        self._tabs = list(tabs) if tabs else []
        self._on_change = on_change
        self._active_tab = active_tab or (self._tabs[0][0]
                                          if self._tabs else None)
        self._tab_widgets = {}  # tab_id → (frame, label, underline)

        self._build()
        self._apply_active_style()

    def _build(self):
        """Build the tab cells + the bottom border."""
        theme = get_theme()
        c = theme.colors

        # Bottom border: a 1px CTkFrame across the full width.
        self._bottom_border = ctk.CTkFrame(
            self, fg_color=c.border_subtle, height=1, corner_radius=0,
        )
        self._bottom_border.grid(row=1, column=0, columnspan=len(self._tabs),
                                 sticky="ew")

        for i, (tab_id, label) in enumerate(self._tabs):
            cell = ctk.CTkFrame(self, fg_color="transparent",
                                corner_radius=0)
            cell.grid(row=0, column=i, sticky="ew")

            tab_label = ctk.CTkLabel(
                cell, text=str(label).upper(),
                font=theme.fonts.caption,
                text_color=c.text_secondary,
                anchor="center", cursor="hand2",
                padx=SPACE_LG, pady=SPACE_MD,
            )
            tab_label.pack(fill="both", expand=True)

            # Active underline (hidden by default; shown when active).
            # CTk 6.0's place() doesn't accept width/height — set them
            # at construction instead. The underline's height (3px) is
            # set on the CTkFrame; relwidth=1.0 stretches it across
            # the tab cell.
            underline = ctk.CTkFrame(cell, fg_color=c.gold, height=3,
                                     corner_radius=0)
            # Place at the bottom of the cell — height comes from
            # the constructor, relwidth stretches horizontally.
            underline.place(relx=0, rely=1.0, anchor="sw",
                            relwidth=1.0)

            self._tab_widgets[tab_id] = (cell, tab_label, underline)

            # Bindings.
            try:
                tab_label.bind("<Button-1>",
                               lambda e, tid=tab_id: self._on_tab_click(tid),
                               add="+")
                cell.bind("<Button-1>",
                          lambda e, tid=tab_id: self._on_tab_click(tid),
                          add="+")
                tab_label.bind("<Enter>",
                               lambda e, tid=tab_id: self._on_tab_enter(tid),
                               add="+")
                tab_label.bind("<Leave>",
                               lambda e, tid=tab_id: self._on_tab_leave(tid),
                               add="+")
            except Exception:
                pass

        # Make all tab columns equal width.
        for i in range(len(self._tabs)):
            self.grid_columnconfigure(i, weight=1, uniform="tabs")

    def _apply_active_style(self):
        """Apply the active/inactive styling per tab."""
        theme = get_theme()
        c = theme.colors
        for tab_id, (cell, label, underline) in self._tab_widgets.items():
            is_active = (tab_id == self._active_tab)
            try:
                if is_active:
                    label.configure(
                        text_color=c.text_primary,
                        font=(theme.fonts.caption[0],
                              theme.fonts.caption[1], "bold"),
                    )
                    underline.place(relx=0, rely=1.0, anchor="sw",
                                    relwidth=1.0)
                else:
                    label.configure(
                        text_color=c.text_secondary,
                        font=theme.fonts.caption,
                    )
                    underline.place_forget()
            except Exception:
                pass

    def _on_tab_click(self, tab_id):
        if tab_id == self._active_tab:
            return
        self._active_tab = tab_id
        self._apply_active_style()
        if self._on_change is not None:
            try:
                self._on_change(tab_id)
            except Exception as e:
                print(f"[TabBar] on_change failed: {e}", flush=True)

    def _on_tab_enter(self, tab_id):
        if tab_id == self._active_tab:
            return
        try:
            theme = get_theme()
            c = theme.colors
            cell, label, _ = self._tab_widgets[tab_id]
            label.configure(text_color=c.text_primary)
            cell.configure(fg_color=tint_to_solid(c.gold_tint,
                                                  c.bg_card_elevated))
        except Exception:
            pass

    def _on_tab_leave(self, tab_id):
        if tab_id == self._active_tab:
            return
        try:
            theme = get_theme()
            c = theme.colors
            cell, label, _ = self._tab_widgets[tab_id]
            label.configure(text_color=c.text_secondary)
            cell.configure(fg_color="transparent")
        except Exception:
            pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_active(self, tab_id):
        """Programmatically activate a tab."""
        self._on_tab_click(tab_id)

    def get_active(self):
        return self._active_tab

    def set_tabs(self, tabs, active_tab=None):
        """Replace the tab list. Re-builds the cells."""
        # Destroy existing.
        for child in self.winfo_children():
            child.destroy()
        self._tab_widgets.clear()
        self._tabs = list(tabs) if tabs else []
        self._active_tab = active_tab or (self._tabs[0][0]
                                          if self._tabs else None)
        self._build()
        self._apply_active_style()
