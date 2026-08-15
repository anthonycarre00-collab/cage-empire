"""CAGE EMPIRE — Phase 2 Component Library (24 components).

Per docs/UI_REDESIGN_VISUAL_PLAN §5 + the Phase 2 spec from the
supervisor. This package is the foundation for Phases 3-6 (screen
redesigns). NO screen code uses these components yet — they ship
behind a feature flag (import only).

GROUP A — 15 structural components (§5.1-§5.16):
  1.  Card               — 3-tier content surface (Flat / Elevated / Accent)
  2.  SectionHeader      — gold left-accent + title + metadata
  3.  DataChip           — 4-variant status pill
  4.  StatBar            — voice-encoded attribute bar (7 tiers)
  5.  FighterRow         — 36px row with hover/select/champ variants
  6.  NewsCard           — topic + headline + body + timestamp
  7.  WatchCard          — Accent card with portrait + voice phrase
  8.  PortraitFrame     — 4 size variants with champion gold border
  9.  HyperlinkLabel    — gold-text clickable label (refactor)
  10. Button             — 4-variant: Primary / Secondary / Danger / Ghost
  11. TabBar             — sub-nav with gold underline on active
  12. CalendarStrip     — horizontal scrollable date strip
  13. Breadcrumb         — navigation trail
  14. EmptyState         — personality-driven empty-state card
  15. ModalDialog        — overlay + Elevated card, slide-in 150ms

GROUP B — 9 visual richness components (the differentiators):
  16. GradientCard       — PIL-composited gradient background
  17. TrendIndicator     — ▲▼ arrow + delta + sparkline
  18. FormMeter          — visual win/loss streak bar (PIL blocks)
  19. MomentumRing       — circular ring that fills clockwise (PIL arc)
  20. AttributeBar       — animated fill + voice phrase tooltip
  21. Sparkline          — reusable mini line-chart (PIL)
  22. StatTile           — large number + trend + sparkline
  23. BeatBar            — Fight Night round/clock bar with pulse
  24. GradientHeader     — PIL gradient banner for screen H1s

Each component lives in its own file. The __init__ re-exports them
for convenient import:

    from ui.widgets.components import Card, Button, GradientHeader

CONVENTIONS compliance:
  §14 — Voice Layer: every component that displays text uses voice
        phrases from the caller. No raw attribute numbers in
        player-facing UI. AttributeBar's `value` param is for bar fill
        width ONLY — never displayed.
  §17 — UI Snapshot Rule: no DB reads. Components are pure UI plumbing.

Theme awareness:
  Every component reads from `get_theme()` at construction time. For
  theme switches (Office ↔ Fight Night), parent screens should
  re-render their components (typically by calling _refresh() which
  recreates them). Phase 2 doesn't wire up live theme-change
  re-rendering at the component level — that's the screens'
  responsibility.
"""

# Group A — structural components.
from .card import Card
from .section_header import SectionHeader
from .data_chip import DataChip
from .stat_bar import StatBar
from .fighter_row import FighterRow
from .news_card import NewsCard
from .watch_card import WatchCard
from .portrait_frame import PortraitFrame
from .hyperlink_label import HyperlinkLabel
from .button import Button
from .tab_bar import TabBar
from .calendar_strip import CalendarStrip
from .breadcrumb import Breadcrumb
from .empty_state import EmptyState
from .modal_dialog import ModalDialog

# Group B — visual richness components.
from .gradient_card import GradientCard
from .trend_indicator import TrendIndicator
from .form_meter import FormMeter
from .momentum_ring import MomentumRing
from .attribute_bar import AttributeBar
from .sparkline import Sparkline
from .stat_tile import StatTile
from .beat_bar import BeatBar
from .gradient_header import GradientHeader


__all__ = [
    # Group A
    "Card",
    "SectionHeader",
    "DataChip",
    "StatBar",
    "FighterRow",
    "NewsCard",
    "WatchCard",
    "PortraitFrame",
    "HyperlinkLabel",
    "Button",
    "TabBar",
    "CalendarStrip",
    "Breadcrumb",
    "EmptyState",
    "ModalDialog",
    # Group B
    "GradientCard",
    "TrendIndicator",
    "FormMeter",
    "MomentumRing",
    "AttributeBar",
    "Sparkline",
    "StatTile",
    "BeatBar",
    "GradientHeader",
]
