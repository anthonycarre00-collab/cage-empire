"""CAGE EMPIRE — FighterTable widget (UI Fix Plan 2 — Phase 3, Fix 11).

A custom CTk-based data table that replaces the ttk.Treeview used by
the Roster + Free Agents screens. Built per AD-5 in
docs/UI_FIX_PLAN_2.md:

  Container = CTkScrollableFrame
  Header row = CTkFrame with CTkLabel per column (clickable for sort)
  Body = CTkFrame per fighter row, with CTkLabel/HyperlinkLabel per cell
  Alternating row colors (bg_surface / bg_surface_elevated)
  Hover effect (lighter background on Enter/Leave)
  Selection (click highlights row, fires callback)
  Configurable columns: caller passes [(id, label, width, anchor), ...]
  Sortable: header click fires callback with (column_id, reverse)

Why replace ttk.Treeview:
  - Treeview can't host rich per-cell widgets (HyperlinkLabels, colored
    badges, icons). It only takes string values + a single tag-based
    row color.
  - Treeview's ttk.Style theming is brittle — the dark Office palette
    has to be re-applied via a global ttk.Style on every refresh.
  - Treeview can't do per-cell font/color variation (e.g., gold for
    champion names, crimson for losing streaks).
  - HyperlinkLabel (Fix 5) needs to live inside a CTk widget tree —
    embedding it inside a Treeview row isn't supported.

  The custom widget trades Treeview's virtualized rendering (good for
  10k+ rows) for full CTk integration (good for the 20-row pages the
  Roster + Free Agents already paginate to). Performance is fine: 20
  rows × 6 cells = 120 widgets per page, well within Tk's budget.

CONVENTIONS compliance:
  §14 — Voice Layer: the widget is display-only. It receives already-
        decoded voice phrases from the caller (Roster/Free Agents
        screens). It never queries the DB or decodes cache values
        itself. The cell text is whatever the caller passes.
  §17 — UI Snapshot Rule: the widget doesn't read the DB. It just
        renders the row data the caller provides.

Usage (Roster / Free Agents):
  from ui.widgets.fighter_table import FighterTable, Column

  table = FighterTable(
      parent,
      columns=[
          Column("name", "Name", 220, "w", hyperlink=True),
          Column("age", "Age", 50, "center"),
          Column("wc", "WC", 60, "center"),
          Column("stage", "Stage", 140, "w"),
          Column("form", "Form", 110, "w"),
          Column("record", "Record", 80, "center"),
      ],
      on_row_click=self._on_row_click,        # optional
      on_row_double_click=self._on_row_double_click,  # optional
      on_sort_click=self._on_sort_click,      # optional
      page_size=20,
  )
  table.pack(fill="both", expand=True)

  # Render rows:
  table.set_rows([
      {"fighter_id": 42, "name": "John Vale", "age": 28,
       "wc": "LW", "stage": "Rising Contender",
       "form": "Heating Up", "record": "18-5-0"},
      # ...
  ])

Architecture:
  - FighterTable(ctk.CTkFrame) — outer container (card-style).
  - _header_row — CTkFrame at the top with one CTkLabel per column.
    Each label has a sort-direction indicator + click binding.
  - _body_frame — CTkScrollableFrame holding the row widgets.
  - _row_widgets — list of dicts tracking each row's frame + cell
    widgets so they can be destroyed + recreated on set_rows.
  - HyperlinkLabel is used for cells where the column has
    hyperlink=True (typically the Name column). Click navigates to
    Fighter Profile via the fighter_id stored on the row.

DESIGN DECISIONS (D-numbers):
  D1  Column config via Column namedtuple. Each column carries an
      id (string, used as the dict key in row data), a label (header
      text), a width (px), an anchor ("w"/"center"/"e"), and a
      hyperlink flag (bool — when True, the cell is rendered as a
      HyperlinkLabel that navigates to the row's fighter_id).
  D2  Row data via list of dicts. Each dict must have keys matching
      the column ids + a "fighter_id" key (for HyperlinkLabel
      navigation + on_row_click callbacks). Missing keys render as
      empty strings (defensive).
  D3  Sort indicator. The header label for the active sort column
      shows a "▲" (ascending) or "▼" (descending) marker. Clicking
      a header fires on_sort_click(column_id, reverse). The caller
      is responsible for re-sorting the row data + calling set_rows
      again — the widget doesn't sort in-place (the caller has the
      domain knowledge of how to sort voice phrases vs numbers).
  D4  Hover + selection. Each row's CTkFrame binds <Enter>/<Leave>
      to swap the background to a hover color (steel-tinted). Click
      (<Button-1>) selects the row (sets the row frame to the gold-
      tinted selected color + fires on_row_click). The selection
      is single-select (clicking a new row deselects the previous).
  D5  Alternating row colors. Even-indexed rows use bg_surface;
      odd-indexed rows use bg_surface_elevated. The hover + selected
      colors override the alternating color when active. The colors
      are read from the theme at render time so theme-change refresh
      picks up the new palette.
  D6  Defensive against missing data. If a row dict is missing a
      column key, the cell renders as "" (empty string). If
      fighter_id is missing, the HyperlinkLabel degrades to a plain
      CTkLabel (no navigation). This keeps the table from crashing
      on partial data (e.g., a free agent with no career stats).
  D7  Empty state. If set_rows is called with an empty list (or
      None), the body shows a single centered label with the
      caller-provided empty_message. Defaults to "No fighters to
      display."
  D8  Theme-change refresh. The widget reads colors/fonts from
      get_theme() at every set_rows + _apply_header_style call.
      Callers that re-render on theme change (state.refresh_all)
      just need to call set_rows again to pick up the new palette.
  D9  Scrollable body. The body is a CTkScrollableFrame so the
      table can grow beyond the viewport without affecting the
      header (the header stays fixed at the top while the body
      scrolls). Page-size callers (Roster pagination = 20) won't
      usually need scrolling, but on small windows the scroll is
      there as a safety net.
  D10 HyperlinkLabel integration. When a column has hyperlink=True,
      the cell is a HyperlinkLabel with the row's fighter_id set.
      Clicking navigates to Fighter Profile (the HyperlinkLabel
      handles this internally via state.set_active_screen). The
      caller's on_row_click callback ALSO fires (single-click
      selects the row visually) — the HyperlinkLabel's fighter
      navigation only fires on a direct click of the name cell, not
      on clicks elsewhere in the row.
"""

from collections import namedtuple

import customtkinter as ctk

from ui.theme import get_theme
from ui.widgets.hyperlink import HyperlinkLabel


# ============================================================
# COLUMN CONFIG (D1)
# ============================================================

# A Column describes one column's display config. The id is the dict
# key the row data uses for this column's value; the label is the
# header text; width is in px; anchor is "w"/"center"/"e"; hyperlink
# flags whether cells should be HyperlinkLabels (Fix 13 — fighter
# names link to Fighter Profile).
Column = namedtuple(
    "Column",
    ["id", "label", "width", "anchor", "hyperlink"],
)
# Provide sensible defaults so callers can omit hyperlink (defaults
# to False — most columns are plain labels).
Column.__new__.__defaults__ = (False,)


# ============================================================
# FIGHTER TABLE
# ============================================================

class FighterTable(ctk.CTkFrame):
    """Custom CTk-based data table for fighter rows.

    See module docstring for the full architecture + D-number
    decisions. The public API is:
      - set_rows(rows, empty_message=None) — render a new page of rows.
      - set_sort_state(column_id, reverse) — update the header sort
        indicator (does NOT re-sort — the caller does that).
      - get_selected_fighter_id() — return the fighter_id of the
        currently-selected row, or None if no row is selected.
      - clear_selection() — deselect any selected row.
    """

    # Hover color: a steel-tinted overlay on top of the alternating
    # row color. Computed once at module load (avoids re-stringifying
    # on every <Enter> event).
    _HOVER_BG = "#2a2f3a"
    # Selected color: a gold-tinted overlay (subtle — the gold text
    # accents carry the visual weight, not the background).
    _SELECTED_BG = "#3a2f1f"

    def __init__(self, parent, columns, on_row_click=None,
                 on_row_double_click=None, on_sort_click=None,
                 page_size=20, empty_message="No fighters to display.",
                 **kwargs):
        """Initialize the FighterTable.

        Args:
            parent: the parent CTk widget.
            columns: list of Column namedtuples (D1).
            on_row_click: optional callback(fighter_id) fired on
                single-click of any row. The HyperlinkLabel cells
                also fire their own navigation independently.
            on_row_double_click: optional callback(fighter_id) fired
                on double-click of any row.
            on_sort_click: optional callback(column_id, reverse)
                fired when a header label is clicked. The widget
                tracks sort state internally + updates the indicator;
                the caller re-sorts the row data + calls set_rows.
            page_size: max rows to render (informational — the
                caller is responsible for paginating; the widget
                just renders whatever set_rows receives).
            empty_message: text to show when set_rows receives an
                empty list (D7).
            **kwargs: forwarded to CTkFrame.
        """
        super().__init__(parent, **kwargs)

        if not columns:
            raise ValueError("FighterTable requires at least one column")

        self._columns = list(columns)
        self._on_row_click = on_row_click
        self._on_row_double_click = on_row_double_click
        self._on_sort_click = on_sort_click
        self._page_size = page_size
        self._empty_message = empty_message

        # Sort state — caller updates via set_sort_state.
        self._sort_column_id = None
        self._sort_reverse = False

        # Selection state — single-select. Tracks the currently
        # selected row's fighter_id + the row frame widget (so we
        # can restore its background when another row is selected).
        self._selected_fighter_id = None
        self._selected_row_frame = None
        self._selected_row_index = -1  # for restoring alternating bg

        # Row widget tracking — destroyed + recreated on set_rows.
        self._row_widgets = []  # list of dicts: {frame, cells, fighter_id, index}

        # Theme the outer card.
        theme = get_theme()
        self.configure(fg_color=theme.colors.bg_surface, corner_radius=8)

        # ---- Header row (D3) ----
        self._header_row = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_surface_elevated,
            corner_radius=0, height=36,
        )
        self._header_row.pack(side="top", fill="x")
        self._header_row.pack_propagate(False)  # keep the 36px height
        self._header_labels = {}  # column_id → CTkLabel
        self._build_header()

        # ---- Body (scrollable) ----
        self._body = ctk.CTkScrollableFrame(
            self, fg_color=theme.colors.bg_surface, corner_radius=0,
        )
        self._body.pack(side="top", fill="both", expand=True)

        # ---- Empty-state label (D7) ----
        # Built lazily by _render_empty_state when needed.
        self._empty_label = None

    # ============================================================
    # HEADER (D3)
    # ============================================================

    def _build_header(self):
        """Build the header row with one CTkLabel per column.

        Each label is bound to <Button-1> → _on_header_click. The
        active sort column's label gets a "▲"/"▼" suffix.
        """
        theme = get_theme()
        for col in self._columns:
            # Anchors: CTkLabel uses anchor="w"/"center"/"e" but
            # we wrap the label in a fixed-width CTkFrame so the
            # column widths are respected.
            cell = ctk.CTkFrame(
                self._header_row, fg_color="transparent",
                width=col.width,
            )
            cell.pack(side="left", fill="y")
            cell.pack_propagate(False)  # respect col.width

            label = ctk.CTkLabel(
                cell, text=col.label,
                font=(theme.fonts.body_small[0],
                      theme.fonts.body_small[1] + 1, "bold"),
                text_color=theme.colors.gold,
                anchor=self._tk_anchor(col.anchor),
            )
            label.pack(fill="both", expand=True, padx=8)

            # Click to sort. Hand cursor for affordance.
            try:
                label.configure(cursor="hand2")
            except Exception:
                pass
            label.bind("<Button-1>",
                       lambda e, c=col: self._on_header_click(c))

            self._header_labels[col.id] = label

    def _on_header_click(self, col):
        """Handle header click — toggle sort + fire callback (D3)."""
        if self._sort_column_id == col.id:
            # Same column — flip direction.
            new_reverse = not self._sort_reverse
        else:
            # New column — start ascending.
            new_reverse = False
        self.set_sort_state(col.id, new_reverse)
        if self._on_sort_click is not None:
            try:
                self._on_sort_click(col.id, new_reverse)
            except Exception as e:
                print(f"Warning: FighterTable sort callback failed: {e}",
                      flush=True)

    def set_sort_state(self, column_id, reverse):
        """Update the header sort indicator (D3).

        Does NOT re-sort the rows — the caller does that + calls
        set_rows. This method just updates the visual indicator on
        the header labels.
        """
        self._sort_column_id = column_id
        self._sort_reverse = bool(reverse)
        try:
            for cid, label in self._header_labels.items():
                # Strip any existing ▲/▼ suffix.
                text = label.cget("text").rstrip(" ▲▼")
                if cid == column_id:
                    text += " ▼" if reverse else " ▲"
                label.configure(text=text)
        except Exception as e:
            print(f"Warning: FighterTable sort indicator update failed: {e}",
                  flush=True)

    # ============================================================
    # ROWS (D2, D4, D5, D6, D7)
    # ============================================================

    def set_rows(self, rows, empty_message=None):
        """Render a new page of rows.

        Args:
            rows: list of dicts. Each dict's keys must match the
                column ids (missing keys → empty cell, D6). Each
                dict should also have a "fighter_id" key for
                HyperlinkLabel navigation + on_row_click.
            empty_message: optional override of the default empty
                message (D7). Used when the caller knows the
                specific reason the list is empty (e.g., "Your
                roster is empty. Sign some free agents.").
        """
        try:
            # Destroy old row widgets.
            self._destroy_rows()

            if empty_message:
                self._empty_message = empty_message

            if not rows:
                self._render_empty_state()
                return

            # Clear any empty-state label that may have been shown
            # previously.
            self._hide_empty_state()

            theme = get_theme()
            for i, row_data in enumerate(rows):
                fighter_id = row_data.get("fighter_id")
                # Alternating row color (D5).
                base_bg = (theme.colors.bg_surface
                           if i % 2 == 0
                           else theme.colors.bg_surface_elevated)

                row_frame = ctk.CTkFrame(
                    self._body, fg_color=base_bg, corner_radius=0,
                    height=32,
                )
                row_frame.pack(side="top", fill="x")
                row_frame.pack_propagate(False)

                # Build the cells.
                cells = []
                for col in self._columns:
                    value = row_data.get(col.id, "")
                    if value is None:
                        value = ""
                    cell_text = str(value)

                    cell = ctk.CTkFrame(
                        row_frame, fg_color="transparent",
                        width=col.width,
                    )
                    cell.pack(side="left", fill="y")
                    cell.pack_propagate(False)

                    if col.hyperlink and fighter_id is not None:
                        # HyperlinkLabel cell (D10). Clicking navigates
                        # to Fighter Profile via the HyperlinkLabel's
                        # built-in handler. We also bind row-click
                        # selection on the cell.
                        label = HyperlinkLabel(
                            cell, text=cell_text,
                            fighter_id=fighter_id,
                            font=theme.fonts.body_small,
                            anchor=self._tk_anchor(col.anchor),
                        )
                        label.pack(fill="both", expand=True, padx=8)
                    else:
                        # Plain label cell.
                        label = ctk.CTkLabel(
                            cell, text=cell_text,
                            font=theme.fonts.body_small,
                            text_color=theme.colors.text_primary,
                            anchor=self._tk_anchor(col.anchor),
                        )
                        label.pack(fill="both", expand=True, padx=8)

                    cells.append({"frame": cell, "label": label})

                # Hover + click bindings on the row frame + every
                # child cell (so the player can click anywhere in
                # the row, not just on a label). Use add="+" so we
                # don't displace the HyperlinkLabel's own bindings.
                row_frame.bind("<Enter>",
                               lambda e, rf=row_frame, bg=base_bg:
                                   self._on_row_enter(rf, bg),
                               add="+")
                row_frame.bind("<Leave>",
                               lambda e, rf=row_frame, bg=base_bg:
                                   self._on_row_leave(rf, bg),
                               add="+")
                row_frame.bind("<Button-1>",
                               lambda e, fid=fighter_id:
                                   self._on_row_button1(fid),
                               add="+")
                if self._on_row_double_click is not None:
                    row_frame.bind("<Double-Button-1>",
                                   lambda e, fid=fighter_id:
                                       self._on_row_double(fid),
                                   add="+")
                # Propagate the same bindings to the cell frames AND
                # the label widgets themselves so the entire row is
                # interactive. CRITICAL: Tk does NOT propagate mouse
                # events from child widgets (labels) to parent frames
                # by default — without these label bindings, clicking
                # on the TEXT of any non-Name cell silently does
                # nothing (P0-2 in UI Implementation Plan v3).
                # `add="+"` preserves the HyperlinkLabel's own
                # <Button-1> + <Enter>/<Leave> handlers (it appends
                # our handler rather than replacing).
                for c in cells:
                    c["frame"].bind("<Enter>",
                                    lambda e, rf=row_frame, bg=base_bg:
                                        self._on_row_enter(rf, bg),
                                    add="+")
                    c["frame"].bind("<Leave>",
                                    lambda e, rf=row_frame, bg=base_bg:
                                        self._on_row_leave(rf, bg),
                                    add="+")
                    c["frame"].bind("<Button-1>",
                                    lambda e, fid=fighter_id:
                                        self._on_row_button1(fid),
                                    add="+")
                    if self._on_row_double_click is not None:
                        c["frame"].bind("<Double-Button-1>",
                                        lambda e, fid=fighter_id:
                                            self._on_row_double(fid),
                                        add="+")
                    # Bind on the LABEL too — Tk doesn't bubble mouse
                    # events from child to parent, so the label would
                    # otherwise swallow the click (hover effects + row
                    # selection would only fire when the player clicks
                    # the cell's padding, not the text itself). The
                    # HyperlinkLabel's own handlers stay intact thanks
                    # to add="+".
                    lbl = c["label"]
                    lbl.bind("<Enter>",
                             lambda e, rf=row_frame, bg=base_bg:
                                 self._on_row_enter(rf, bg),
                             add="+")
                    lbl.bind("<Leave>",
                             lambda e, rf=row_frame, bg=base_bg:
                                 self._on_row_leave(rf, bg),
                             add="+")
                    lbl.bind("<Button-1>",
                             lambda e, fid=fighter_id:
                                 self._on_row_button1(fid),
                             add="+")
                    if self._on_row_double_click is not None:
                        lbl.bind("<Double-Button-1>",
                                 lambda e, fid=fighter_id:
                                     self._on_row_double(fid),
                                 add="+")

                self._row_widgets.append({
                    "frame": row_frame,
                    "cells": cells,
                    "fighter_id": fighter_id,
                    "index": i,
                    "base_bg": base_bg,
                })
        except Exception as e:
            print(f"Warning: FighterTable.set_rows failed: {e}",
                  flush=True)

    def _destroy_rows(self):
        """Destroy all current row widgets + reset selection (D8)."""
        for row in self._row_widgets:
            try:
                row["frame"].destroy()
            except Exception:
                pass
        self._row_widgets = []
        self._selected_row_frame = None
        self._selected_row_index = -1
        # Keep _selected_fighter_id so the caller can preserve
        # selection across refreshes if they want — but the visual
        # highlight is gone until the player clicks again.

    def _render_empty_state(self):
        """Show the empty-state label (D7)."""
        try:
            if self._empty_label is None:
                theme = get_theme()
                self._empty_label = ctk.CTkLabel(
                    self._body,
                    text=self._empty_message,
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    justify="center",
                    wraplength=600,
                )
            else:
                self._empty_label.configure(text=self._empty_message)
            self._empty_label.pack(expand=True, fill="both",
                                    padx=20, pady=40)
        except Exception as e:
            print(f"Warning: FighterTable empty-state render failed: {e}",
                  flush=True)

    def _hide_empty_state(self):
        """Hide the empty-state label if it was shown."""
        try:
            if self._empty_label is not None:
                self._empty_label.pack_forget()
        except Exception:
            pass

    # ============================================================
    # HOVER + SELECTION (D4)
    # ============================================================

    def _on_row_enter(self, row_frame, base_bg):
        """<Enter> handler — apply hover background (D4).

        Skip if this row is the selected row (the selected background
        takes precedence over hover).
        """
        try:
            if row_frame is self._selected_row_frame:
                return
            row_frame.configure(fg_color=self._HOVER_BG)
        except Exception:
            pass

    def _on_row_leave(self, row_frame, base_bg):
        """<Leave> handler — restore the row's base background (D4)."""
        try:
            if row_frame is self._selected_row_frame:
                # Selected row keeps its selected color.
                row_frame.configure(fg_color=self._SELECTED_BG)
            else:
                row_frame.configure(fg_color=base_bg)
        except Exception:
            pass

    def _on_row_button1(self, fighter_id):
        """<Button-1> handler — select the row + fire callback (D4)."""
        try:
            self._select_row_by_fighter_id(fighter_id)
        except Exception:
            pass
        if self._on_row_click is not None:
            try:
                self._on_row_click(fighter_id)
            except Exception as e:
                print(f"Warning: FighterTable row-click callback failed: {e}",
                      flush=True)

    def _on_row_double(self, fighter_id):
        """<Double-Button-1> handler — fire the double-click callback."""
        if self._on_row_double_click is not None:
            try:
                self._on_row_double_click(fighter_id)
            except Exception as e:
                print(f"Warning: FighterTable double-click callback failed: {e}",
                      flush=True)

    def _select_row_by_fighter_id(self, fighter_id):
        """Select the row matching fighter_id (D4).

        Single-select: deselects the previously-selected row (restores
        its alternating background) + selects the new row (sets the
        selected background). No-op if fighter_id doesn't match any
        row (defensive — the click handler may have stale data after
        a refresh).
        """
        # Find the new row.
        new_row = None
        for row in self._row_widgets:
            if row["fighter_id"] == fighter_id:
                new_row = row
                break
        if new_row is None:
            return

        # Deselect the old row.
        if self._selected_row_frame is not None:
            try:
                old_row = next(
                    (r for r in self._row_widgets
                     if r["frame"] is self._selected_row_frame),
                    None,
                )
                if old_row is not None:
                    self._selected_row_frame.configure(
                        fg_color=old_row["base_bg"])
            except Exception:
                pass

        # Select the new row.
        try:
            new_row["frame"].configure(fg_color=self._SELECTED_BG)
        except Exception:
            pass
        self._selected_row_frame = new_row["frame"]
        self._selected_row_index = new_row["index"]
        self._selected_fighter_id = fighter_id

    # ============================================================
    # PUBLIC API — selection helpers
    # ============================================================

    def get_selected_fighter_id(self):
        """Return the fighter_id of the selected row, or None."""
        return self._selected_fighter_id

    def clear_selection(self):
        """Deselect any selected row."""
        if self._selected_row_frame is not None:
            try:
                old_row = next(
                    (r for r in self._row_widgets
                     if r["frame"] is self._selected_row_frame),
                    None,
                )
                if old_row is not None:
                    self._selected_row_frame.configure(
                        fg_color=old_row["base_bg"])
            except Exception:
                pass
        self._selected_row_frame = None
        self._selected_row_index = -1
        self._selected_fighter_id = None

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _tk_anchor(anchor):
        """Translate our anchor shorthand to Tk anchor values."""
        if anchor == "w":
            return "w"
        if anchor == "e":
            return "e"
        return "center"
