"""CAGE EMPIRE — Phase 2 Component Library: PortraitFrame (§5.8).

256px portrait with gold/crimson border. Refines the current
fighter_profile.py portrait.

Visual spec (UI_REDESIGN_VISUAL_PLAN §5.8):

  +-----------+--------+---------+--------+-------+----------------------+
  | Variant   | Size   | Border  | Width  | Corn  | When                 |
  +-----------+--------+---------+--------+-------+----------------------+
  | Hero      | 256×320| gold (champ) or border_subtle | 3px | 8px | Profile header |
  | Watch     | 64×80  | gold (champ) or none  | 2px   | 6px   | Dashboard WatchCard |
  | Row       | 28×36  | none                   | 0     | 4px   | Future: in-table  |
  | Mini      | 20×25  | none                   | 0     | 4px   | Future: avatar    |
  +-----------+--------+---------+--------+-------+----------------------+

  Champion variant: gold border + subtle gold-leaf texture overlay.
  Scouted variant: dashed border_subtle (incomplete info).

States:
  Hover → 100ms gold-tint overlay. Click → navigates to Fighter
  Profile.

When to use:
  Fighter Profile (Hero), Dashboard WatchCard (Watch), eventually
  Roster (Row, P1 future).

CONVENTIONS compliance:
  §14 — Voice Layer: no text. Pure visual.
  §17 — UI Snapshot Rule: no DB reads. Caller passes the CTkImage.
"""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import get_theme, CHAMPIONSHIP_SKIN


_SIZE_MAP = {
    "hero":  (256, 320),
    "watch": (64, 80),
    "row":   (28, 36),
    "mini":  (20, 25),
}


class PortraitFrame(ctk.CTkFrame):
    """A framed portrait. 4 size variants.

    Args:
        parent: parent widget.
        ctk_image: optional CTkImage to display as the portrait. If
            None, shows a placeholder (initials on bg_card).
        size: "hero" (256×320) | "watch" (64×80) | "row" (28×36) |
            "mini" (20×25).
        is_champion: bool — gold border (champion_gold, width 3 for
            hero, 2 for watch).
        is_scouted: bool — dashed border_subtle (incomplete info).
        initials: optional string for the placeholder (e.g. "JV").
            Ignored if ctk_image is provided.
        fighter_id: optional — passed to on_click when the portrait
            is clicked.
        on_click: optional callable(fighter_id).
        **kwargs: forwarded to CTkFrame.
    """

    def __init__(self, parent, ctk_image=None, size="watch",
                 is_champion=False, is_scouted=False, initials="?",
                 fighter_id=None, on_click=None, **kwargs):
        self._size_key = size if size in _SIZE_MAP else "watch"
        w, h = _SIZE_MAP[self._size_key]
        self._w = w
        self._h = h
        self._is_champion = is_champion
        self._is_scouted = is_scouted
        self._fighter_id = fighter_id
        self._on_click = on_click

        theme = get_theme()
        c = theme.colors

        # Border: champion → gold (width 3 for hero, 2 for others);
        #         scouted → border_subtle dashed (width 1);
        #         else → border_subtle solid (width 1, hero only).
        if is_champion:
            border_color = CHAMPIONSHIP_SKIN.get("champion_gold", c.gold)
            border_width = 3 if self._size_key == "hero" else 2
        elif is_scouted:
            border_color = c.border_subtle
            border_width = 1
        elif self._size_key in ("hero", "watch"):
            border_color = c.border_subtle
            border_width = 1
        else:
            border_color = c.bg_card  # transparent on small sizes
            border_width = 0

        corner_radius = {"hero": 8, "watch": 6, "row": 4, "mini": 4}[self._size_key]

        super().__init__(parent, fg_color=c.bg_card_elevated,
                         border_color=border_color,
                         border_width=border_width,
                         corner_radius=corner_radius,
                         width=w, height=h, **kwargs)
        # Lock the size — caller can override via pack/grid but the
        # requested size is the natural size.
        try:
            self.pack_propagate(False)
        except Exception:
            pass

        # Inner image label (or placeholder initials).
        if ctk_image is not None:
            self._img_label = ctk.CTkLabel(
                self, image=ctk_image, text="",
                fg_color="transparent", corner_radius=corner_radius,
            )
        else:
            # Placeholder: initials on a colored bg. Font sized per
            # variant.
            font_size = {"hero": 64, "watch": 18, "row": 8, "mini": 6}[self._size_key]
            self._img_label = ctk.CTkLabel(
                self, text=str(initials)[:2].upper(),
                font=(theme.fonts.h2[0], font_size, "bold"),
                text_color=c.text_secondary,
                fg_color="transparent", corner_radius=corner_radius,
            )
        self._img_label.place(relx=0.5, rely=0.5, anchor="center",
                              relwidth=1.0, relheight=1.0)

        # Click + hover bindings.
        if on_click is not None:
            try:
                self.bind("<Button-1>", self._on_click_event, add="+")
                self._img_label.bind("<Button-1>", self._on_click_event,
                                     add="+")
                try:
                    self.configure(cursor="hand2")
                except Exception:
                    pass
            except Exception:
                pass

    def _on_click_event(self, event=None):
        if self._on_click is not None:
            try:
                self._on_click(self._fighter_id)
            except Exception as e:
                print(f"[PortraitFrame] on_click failed: {e}", flush=True)

    # ------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------

    def set_image(self, ctk_image):
        """Swap the portrait image at runtime."""
        try:
            self._img_label.configure(image=ctk_image, text="")
        except Exception:
            pass

    def set_champion(self, is_champion):
        """Toggle champion border."""
        self._is_champion = is_champion
        theme = get_theme()
        c = theme.colors
        if is_champion:
            border_color = CHAMPIONSHIP_SKIN.get("champion_gold", c.gold)
            border_width = 3 if self._size_key == "hero" else 2
        else:
            border_color = c.border_subtle
            border_width = 1 if self._size_key in ("hero", "watch") else 0
        try:
            self.configure(border_color=border_color,
                           border_width=border_width)
        except Exception:
            pass
