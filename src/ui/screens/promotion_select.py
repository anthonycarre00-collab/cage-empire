"""CAGE EMPIRE — Promotion Selection Screen (startup screen).

Shown when the game first launches. Lets the player choose which
promotion to manage — like Football Manager's club selection screen.

The player picks ONE promotion. That becomes their player_promotion_id
in GameState. All subsequent screens (Dashboard, Roster, etc.) read
from state.get_player_promotion_id().

Per the user's design: "The aim has always been to allow the player
to 'take over' at any of the existing promotions."
"""
import sqlite3
import customtkinter as ctk

from ui.theme import get_theme


class PromotionSelectScreen(ctk.CTkFrame):
    """Startup screen — choose which promotion to manage."""

    def __init__(self, parent, on_select_callback, **kwargs):
        """
        Args:
            parent: the parent widget
            on_select_callback: called with (promotion_id) when the player
                                selects a promotion
        """
        super().__init__(parent, **kwargs)
        self._on_select = on_select_callback
        self._conn = None
        self._promo_buttons = {}
        self._build()

    def set_conn(self, conn):
        """Set the DB connection and refresh the promotion list."""
        self._conn = conn
        self._refresh()

    def _build(self):
        """Build the screen layout."""
        theme = get_theme()

        # Title
        title = ctk.CTkLabel(
            self,
            text="CHOOSE YOUR PROMOTION",
            font=theme.fonts.h1,
            text_color=theme.colors.gold,
        )
        title.pack(pady=(40, 10))

        subtitle = ctk.CTkLabel(
            self,
            text="Which promotion will you take over?",
            font=theme.fonts.body,
            text_color=theme.colors.text_secondary,
        )
        subtitle.pack(pady=(0, 30))

        # Scrollable frame for promotion cards
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.colors.bg_surface,
            corner_radius=8,
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=40, pady=(0, 20))

    def _refresh(self):
        """Re-query promotions and render cards."""
        if not self._conn:
            return

        theme = get_theme()

        # Clear old cards
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._promo_buttons = {}

        # Get all promotions with roster info
        promos = self._conn.execute("""
            SELECT p.promotion_id, p.name, p.size_tier, p.current_cash,
                   p.reputation, p.fan_trust,
                   COUNT(f.fighter_id) as roster_size,
                   (SELECT COUNT(*) FROM titles t WHERE t.promotion_id = p.promotion_id AND t.is_vacant = 0) as champions
            FROM promotions p
            LEFT JOIN fighters f ON p.promotion_id = f.current_promotion_id AND f.is_active = 1
            GROUP BY p.promotion_id
            ORDER BY CASE p.size_tier WHEN 'major' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END,
                     p.name
        """).fetchall()

        for row in promos:
            promo_id, name, tier, cash, rep, trust, roster, champs = row

            # Create a card frame for this promotion
            card = ctk.CTkFrame(
                self.scroll_frame,
                fg_color=theme.colors.bg_surface_elevated,
                corner_radius=8,
                border_width=2,
                border_color=theme.colors.bg_border,
            )
            card.pack(fill="x", padx=10, pady=8)

            # Promotion name + tier
            tier_label_map = {
                "major": "MAJOR — Top tier promotion",
                "mid": "MID — Established regional/national promotion",
                "small": "SMALL — Regional grassroots promotion",
            }
            tier_text = tier_label_map.get(tier, tier.upper())

            name_label = ctk.CTkLabel(
                card,
                text=name,
                font=theme.fonts.h2,
                text_color=theme.colors.text_primary,
                anchor="w",
            )
            name_label.pack(fill="x", padx=15, pady=(12, 2))

            tier_label = ctk.CTkLabel(
                card,
                text=tier_text,
                font=theme.fonts.caption,
                text_color=theme.colors.text_tertiary,
                anchor="w",
            )
            tier_label.pack(fill="x", padx=15, pady=(0, 8))

            # Stats row
            cash_str = f"${cash / 1_000_000:.1f}M" if cash and abs(cash) >= 1_000_000 else f"${cash:,.0f}"

            # Reputation as descriptor (not raw number per §14)
            rep_desc = self._reputation_desc(rep)
            trust_desc = self._trust_desc(trust)

            stats_text = (
                f"Roster: {roster} fighters  |  "
                f"Champions: {champs}  |  "
                f"Cash: {cash_str}  |  "
                f"Reputation: {rep_desc}  |  "
                f"Fan Trust: {trust_desc}"
            )

            stats_label = ctk.CTkLabel(
                card,
                text=stats_text,
                font=theme.fonts.body_small,
                text_color=theme.colors.text_secondary,
                anchor="w",
            )
            stats_label.pack(fill="x", padx=15, pady=(0, 10))

            # Difficulty hint based on tier
            difficulty_map = {
                "major": "Easier start — deep roster, big budget, established stars",
                "mid": "Medium difficulty — solid foundation, room to grow",
                "small": "Hard mode — small budget, thin roster, build from scratch",
            }
            diff_text = difficulty_map.get(tier, "")
            if diff_text:
                diff_label = ctk.CTkLabel(
                    card,
                    text=diff_text,
                    font=theme.fonts.caption,
                    text_color=theme.colors.gold if tier == "small" else theme.colors.text_tertiary,
                    anchor="w",
                )
                diff_label.pack(fill="x", padx=15, pady=(0, 10))

            # Select button
            select_btn = ctk.CTkButton(
                card,
                text=f"Take Over {name}",
                font=theme.fonts.h3,
                height=36,
                corner_radius=8,
                fg_color=theme.colors.gold,
                hover_color=theme.colors.crimson,
                text_color=theme.colors.bg_base,
                command=lambda pid=promo_id: self._on_select(pid),
            )
            select_btn.pack(fill="x", padx=15, pady=(0, 15))

    def _reputation_desc(self, rep):
        """Convert raw reputation number to a descriptor (§14)."""
        if rep is None:
            return "Unknown"
        if rep >= 80:
            return "Elite"
        elif rep >= 65:
            return "Highly Respected"
        elif rep >= 50:
            return "Respected"
        elif rep >= 35:
            return "Developing"
        elif rep >= 20:
            return "Struggling"
        else:
            return "Unknown"

    def _trust_desc(self, trust):
        """Convert raw fan trust number to a descriptor (§14)."""
        if trust is None:
            return "Unknown"
        if trust >= 80:
            return "Devoted"
        elif trust >= 65:
            return "Strong"
        elif trust >= 50:
            return "Moderate"
        elif trust >= 35:
            return "Wavering"
        else:
            return "Lost"
