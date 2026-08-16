"""CAGE EMPIRE — Phase 2 Component Library: FighterRow (§5.5).

One row in a FighterTable. 36px height, gold-tint hover, 2px gold left
border on selected. Champion / injured / streak variants.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.5):

  ┌───────────────────────────────────────────────────────────────────────┐
  │ ● John Vale              28  LW  Rising Contender │ Steady   18-5-0   ▶│
  └───────────────────────────────────────────────────────────────────────┘

  - Height: 36px (current 28px is too cramped — VLM "cramped sidebar")
  - Row bg: alternating bg_card / bg_card_elevated
  - Hover bg: gold_tint (composited over the row's base bg)
  - Selected bg: gold_tint + 2px gold left border
  - Active-fighter indicator (left, 6px): dot or chevron — gold if
    champion, crimson if on losing streak, neutral otherwise
  - Cell padding: 8px vertical × 12px horizontal
  - Cell fonts: Name = body_small Bold (gold if hyperlink),
    Age/WC = mono_small, Stage/Form = descriptor_small italic,
    Record = mono_small

States:
  - Default: alternating bg
  - Hover: gold_tint bg, cursor = hand2
  - Selected: gold_tint + gold left border, cursor = hand2
  - Champion variant: gold dot + bolded name + "CHAMP" chip in WC column
  - Injured variant: crimson dot + "(INJ)" chip appended to name
  - On streak variant: chip "W3" / "L2"

When to use:
  Roster, Free Agents, Matchmaking (fighter picker), Past Events (fight
  card list), Training Camps (roster view). Anywhere a list of fighters
  is shown.

NOTE: This is a self-contained row widget. The existing FighterTable
(in src/ui/widgets/fighter_table.py) has its own row rendering that
uses HyperlinkLabel inline. Phase 3-6 will migrate tables to use
FighterRow. For Phase 2, FighterRow is standalone — it doesn't
replace anything yet (no screen code changes per the spec).

CONVENTIONS compliance:
  §14 — Voice Layer: stage + form columns are voice phrases. Record
        + age + WC are NOT attribute values per §14 (they're identity
        strings + career stats — explicitly allowed).
  §17 — UI Snapshot Rule: no DB reads. The row is fed by the caller.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, tint_to_solid, SPACE_SM, SPACE_MD
from .data_chip import DataChip
from .hyperlink_label import HyperlinkLabel


_ROW_HEIGHT = 36


class FighterRow(ctk.CTkFrame):
    """One row in a FighterTable.

    Args:
        parent: parent widget (typically a CTkScrollableFrame body).
        fighter_id: the fighter's DB id (passed to on_click).
        name: fighter name string.
        age: age (int or str).
        weight_class: weight class code (e.g. "LW", "MW").
        stage: voice phrase for the fighter's career stage
            (e.g. "Rising Contender").
        form: voice phrase for form (e.g. "Heating Up", "Steady",
            "Sliding").
        record: career record string (e.g. "18-5-0").
        is_champion: bool — champion variant (gold dot + CHAMP chip).
        is_injured: bool — injured variant (crimson dot + INJ chip).
        streak: optional ("W3" / "L2" / None) — streak chip.
        is_even: bool — alternating row color (True = even index).
        is_selected: bool — selected state on init.
        on_click: callable(fighter_id) — fired on row click.
        **kwargs: forwarded to CTkFrame.

    Layout (grid, 7 columns):
      [dot | name (link) | age | wc | stage | form | record | chevron]
    """

    def __init__(self, parent, fighter_id=None, name="", age="",
                 weight_class="", stage="", form="", record="",
                 is_champion=False, is_injured=False, streak=None,
                 is_even=True, is_selected=False, on_click=None,
                 **kwargs):
        super().__init__(parent, corner_radius=0, height=_ROW_HEIGHT,
                         **kwargs)
        self._fighter_id = fighter_id
        self._is_champion = is_champion
        self._is_injured = is_injured
        self._streak = streak
        self._is_even = is_even
        self._is_selected = is_selected
        self._on_click = on_click

        self._build_cells(name, age, weight_class, stage, form, record)
        self._apply_state()

        # Bind click on the whole row (and on every child for hit-area).
        try:
            self.bind("<Button-1>", self._on_click_event, add="+")
            self.bind("<Enter>", self._on_enter, add="+")
            self.bind("<Leave>", self._on_leave, add="+")
            for child in self.winfo_children():
                child.bind("<Button-1>", self._on_click_event, add="+")
                child.bind("<Enter>", self._on_enter, add="+")
                child.bind("<Leave>", self._on_leave, add="+")
        except Exception:
            pass

    # ------------------------------------------------------------
    # CELL CONSTRUCTION
    # ------------------------------------------------------------

    def _build_cells(self, name, age, weight_class, stage, form, record):
        theme = get_theme()
        c = theme.colors

        # Grid layout: dot(20) name(220) age(50) wc(60) stage(160) form(110) record(80)
        self.grid_columnconfigure(0, weight=0)  # dot
        self.grid_columnconfigure(1, weight=1)  # name (expands)
        # Right-aligned cells: fixed widths.
        cols = [
            ("dot", 20, "center"),
            ("name", 220, "w"),
            ("age", 50, "center"),
            ("wc", 60, "center"),
            ("stage", 160, "w"),
            ("form", 110, "w"),
            ("record", 80, "center"),
            ("chevron", 24, "center"),
        ]
        for i, (_, w, _) in enumerate(cols):
            if i > 1:
                self.grid_columnconfigure(i, weight=0, minsize=w,
                                          uniform="row")

        # Active-fighter dot (col 0).
        dot_color = c.gold if self._is_champion else (
            c.crimson if self._is_injured else c.steel
        )
        self._dot = ctk.CTkFrame(self, fg_color=dot_color, corner_radius=3,
                                 width=6, height=6)
        self._dot.grid(row=0, column=0, padx=(SPACE_MD, 0), pady=8)

        # Name (col 1) — HyperlinkLabel so the name navigates.
        # If no fighter_id, fall back to a plain label.
        if self._fighter_id is not None:
            self._name_label = HyperlinkLabel(
                self, text=name, fighter_id=self._fighter_id,
                on_click=self._on_name_click,
                font=(theme.fonts.body_small[0],
                      theme.fonts.body_small[1], "bold"),
                anchor="w",
            )
        else:
            self._name_label = ctk.CTkLabel(
                self, text=name,
                font=(theme.fonts.body_small[0],
                      theme.fonts.body_small[1], "bold"),
                text_color=c.text_primary, anchor="w",
            )
        self._name_label.grid(row=0, column=1, sticky="ew",
                              padx=(SPACE_SM, SPACE_SM))

        # Injured chip appended to name area (placed in the same cell).
        if self._is_injured:
            inj_chip = DataChip(self, text="INJ", variant="danger")
            # Place into col 1 next to name — use grid with a sub-frame.
            # For simplicity, append to name text:
            try:
                cur = self._name_label.cget("text")
                self._name_label.configure(text=f"{cur}  (INJ)")
            except Exception:
                pass

        # Age (col 2).
        self._age_label = ctk.CTkLabel(
            self, text=str(age) if age != "" else "—",
            font=theme.fonts.mono, text_color=c.text_secondary,
            anchor="center",
        )
        self._age_label.grid(row=0, column=2, sticky="ew", padx=SPACE_SM)

        # Weight class (col 3) — champion shows "CHAMP" chip.
        if self._is_champion:
            wc_chip = DataChip(self, text="CHAMP", variant="champion")
            wc_chip.grid(row=0, column=3, sticky="w", padx=SPACE_SM)
        else:
            self._wc_label = ctk.CTkLabel(
                self, text=weight_class, font=theme.fonts.mono,
                text_color=c.text_secondary, anchor="center",
            )
            self._wc_label.grid(row=0, column=3, sticky="ew", padx=SPACE_SM)

        # Stage (col 4) — voice phrase.
        self._stage_label = ctk.CTkLabel(
            self, text=stage, font=theme.fonts.body_small,
            text_color=c.text_secondary, anchor="w",
        )
        self._stage_label.grid(row=0, column=4, sticky="ew", padx=SPACE_SM)

        # Form (col 5) — voice phrase, italic.
        # If streak provided, show as a chip appended to the form text.
        form_display = form
        if self._streak:
            form_display = f"{form}  {self._streak}"
        self._form_label = ctk.CTkLabel(
            self, text=form_display,
            font=(theme.fonts.descriptor[0],
                  theme.fonts.descriptor[1], "italic"),
            text_color=c.text_primary, anchor="w",
        )
        self._form_label.grid(row=0, column=5, sticky="ew", padx=SPACE_SM)

        # Record (col 6).
        self._record_label = ctk.CTkLabel(
            self, text=record, font=theme.fonts.mono,
            text_color=c.text_primary, anchor="center",
        )
        self._record_label.grid(row=0, column=6, sticky="ew", padx=SPACE_SM)

        # Chevron (col 7) — visible on hover/selected.
        self._chevron = ctk.CTkLabel(
            self, text="▶", font=theme.fonts.body_small,
            text_color=c.gold, anchor="center",
        )
        # Show chevron only if selected (caller can toggle).
        if self._is_selected:
            self._chevron.grid(row=0, column=7, padx=(0, SPACE_SM))

        self.grid_propagate(False)
        self.configure(height=_ROW_HEIGHT)

    def _apply_state(self):
        """Apply the bg + border for the current state."""
        theme = get_theme()
        c = theme.colors
        if self._is_selected:
            fg = tint_to_solid(c.gold_tint, c.bg_card_elevated)
            border_w = 2
            border_color = c.gold
        elif self._is_even:
            fg = c.bg_card_elevated
            border_w = 0
            border_color = c.bg_card_elevated
        else:
            fg = c.bg_card
            border_w = 0
            border_color = c.bg_card
        try:
            self.configure(fg_color=fg, border_width=border_w,
                           border_color=border_color)
        except Exception:
            pass

    # ------------------------------------------------------------
    # EVENT HANDLERS
    # ------------------------------------------------------------

    def _on_enter(self, event=None):
        """Hover → gold_tint bg (unless selected)."""
        if self._is_selected:
            return
        try:
            theme = get_theme()
            c = theme.colors
            self.configure(fg_color=tint_to_solid(c.gold_tint,
                                                  c.bg_card_elevated))
            try:
                self.configure(cursor="hand2")
            except Exception:
                pass
        except Exception:
            pass

    def _on_leave(self, event=None):
        """Restore resting bg."""
        if self._is_selected:
            return
        self._apply_state()
        try:
            self.configure(cursor="")
        except Exception:
            pass

    def _on_click_event(self, event=None):
        """Row click → toggle select + fire on_click(fighter_id)."""
        self.set_selected(not self._is_selected)
        if self._on_click is not None:
            try:
                self._on_click(self._fighter_id)
            except Exception as e:
                print(f"[FighterRow] on_click failed: {e}", flush=True)

    def _on_name_click(self, _fighter_id):
        """HyperlinkLabel fires this — pass through to on_click."""
        # Don't toggle row selection here — the hyperlink navigates
        # to Fighter Profile. The row click handler still fires
        # (the binding is add="+"), but we let the hyperlink's
        # own navigation take precedence.
        if self._on_click is not None:
            try:
                self._on_click(self._fighter_id)
            except Exception:
                pass

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_selected(self, selected):
        """Toggle the selected state."""
        self._is_selected = selected
        self._apply_state()
        # Show / hide chevron.
        try:
            if selected:
                self._chevron.grid(row=0, column=7, padx=(0, SPACE_SM))
            else:
                self._chevron.grid_forget()
        except Exception:
            pass

    def get_fighter_id(self):
        return self._fighter_id
