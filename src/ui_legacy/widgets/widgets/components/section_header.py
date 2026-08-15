"""CAGE EMPIRE — Phase 2 Component Library: SectionHeader (§5.2).

A section title with a gold left-accent bar.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.2):

    █▌ THE EMPIRE — Top Story                              Mon 14 Sep ▶

  - Left accent bar: 3px wide × 20px tall, gold (`gold`), vertically
    centered with the title text.
  - Title: `display_small` (Oswald 24px, +0.02em tracking),
    `text_primary`. Title is ALWAYS UPPERCASE.
  - Right metadata: `caption` (Inter 11px uppercase), `text_secondary`.
  - Container: transparent bg, no border, 0px corner radius, 8px
    bottom margin (caller applies).

States: None. Static component.

When to use:
  Top of every major section within a screen. A typical screen has
  3-6 SectionHeaders. The accent bar is the visual anchor that tells
  the player "this is a new section."

CONVENTIONS compliance:
  §14 — Voice Layer: the title + metadata strings are caller-provided
        (voice phrases, not raw values).
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, SPACE_SM


class SectionHeader(ctk.CTkFrame):
    """A section title with a 3px gold left-accent bar.

    Args:
        parent: parent widget.
        title: the section title text. Will be uppercased.
        metadata: optional right-aligned metadata string (also
            uppercased). Examples: "Mon 14 Sep", "View all ▶".
        accent_color: optional — overrides the left-bar color
            (default gold). Use crimson for danger sections.
        **kwargs: forwarded to CTkFrame.

    Layout (grid):
      [accent_bar] [title ............... metadata]
      col 0 = 3px accent bar
      col 1 = title (sticky w, expand)
      col 2 = metadata (sticky e)
    """

    def __init__(self, parent, title="", metadata=None,
                 accent_color=None, icon_ctk_image=None, **kwargs):
        super().__init__(parent, fg_color="transparent",
                         corner_radius=0, border_width=0, **kwargs)

        theme = get_theme()
        accent = accent_color or theme.colors.gold

        # The 3px accent bar — a tiny CTkFrame, vertically centered.
        self._accent_bar = ctk.CTkFrame(
            self, fg_color=accent, corner_radius=1, width=3,
        )
        self._accent_bar.grid(row=0, column=0, sticky="ns", padx=(0, SPACE_SM))

        # Fix #4 (UI-REDESIGN-DASH-V2): optional icon (e.g., glove/belt)
        # placed between the accent bar and the title.
        col = 1
        if icon_ctk_image is not None:
            self._icon_label = ctk.CTkLabel(
                self, image=icon_ctk_image, text="",
                fg_color="transparent",
            )
            self._icon_label.grid(row=0, column=col, sticky="w",
                                   padx=(0, SPACE_SM))
            col += 1
        else:
            self._icon_label = None

        self._title_label = ctk.CTkLabel(
            self, text=(title or "").upper(),
            font=theme.fonts.display_small,
            text_color=theme.colors.text_primary,
            anchor="w",
        )
        self._title_label.grid(row=0, column=col, sticky="ew",
                                padx=(0, SPACE_SM))
        col += 1

        if metadata:
            self._meta_label = ctk.CTkLabel(
                self, text=str(metadata).upper(),
                font=theme.fonts.caption,
                text_color=theme.colors.text_secondary,
                anchor="e",
            )
            self._meta_label.grid(row=0, column=col, sticky="e")
        else:
            self._meta_label = None

        # Configure the grid: title expands, accent + icon + metadata fixed.
        self.grid_columnconfigure(col - 1 if metadata else col, weight=1)
        # Vertical centering: the accent bar uses sticky="ns" which
        # fills the row height (driven by the title label's height).
        # That gives the bar the same height as the title, which is
        # the visual intent (a "tab" next to the title).
        self.grid_rowconfigure(0, weight=1)

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_title(self, title):
        """Update the title text. Uppercased automatically."""
        try:
            self._title_label.configure(text=(title or "").upper())
        except Exception:
            pass

    def set_metadata(self, metadata):
        """Update or hide the right metadata string."""
        try:
            if metadata:
                if self._meta_label is None:
                    theme = get_theme()
                    self._meta_label = ctk.CTkLabel(
                        self, text=str(metadata).upper(),
                        font=theme.fonts.caption,
                        text_color=theme.colors.text_secondary,
                        anchor="e",
                    )
                    self._meta_label.grid(row=0, column=2, sticky="e")
                else:
                    self._meta_label.configure(text=str(metadata).upper())
            elif self._meta_label is not None:
                self._meta_label.destroy()
                self._meta_label = None
        except Exception:
            pass

    def set_accent_color(self, color):
        """Update the left accent bar color."""
        try:
            self._accent_bar.configure(fg_color=color)
        except Exception:
            pass
