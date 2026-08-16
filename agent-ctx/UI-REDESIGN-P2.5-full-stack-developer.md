# Task ID: UI-REDESIGN-P2.5
**Agent:** Phase 2.5 Dashboard Showcase (full-stack-developer)
**Task:** Rewrite `dashboard.py` using the 24-component Visual Richness Library. Proof-of-concept for Phases 3-6.

## Scope
- Rewrite ONLY `src/ui/screens/dashboard.py`.
- Do NOT touch `roster.py`, `fighter_profile.py`, `free_agents.py`, `app.py`, or existing widgets.
- Preserve all data queries (`_refresh_*`, `_query_*`, `_find_hottest_streak_fighter`, `_lookup_fighter_watch_data`).
- Preserve `_refresh()` callback signature (registered with GameState).
- Preserve screen registration: `register_screen("dashboard", instance, instance._refresh)`.

## Sections (top to bottom, per spec §6.1)
1. **GradientHeader** (gold) — "THE EMPIRE" + subtitle sim-date + promotion.
2. **Top Story** — SectionHeader + GradientCard(gold, 2px gold border). Eyebrow + headline + body + topic chips + "Read full story →" hyperlink.
3. **Promotion Status** — SectionHeader + 5 StatTiles (cash w/ sparkline + trend, reputation voice phrase, fan trust voice phrase, roster count + trend, champions count + trend).
4. **Next Event** — SectionHeader + Card/Flat with event details + 2 buttons (Build Card primary, Matchmaking secondary). EmptyState if no event.
5. **Fighter Watch** — SectionHeader + 3 WatchCards (Top Prospect gold, Hottest Streak gold, Biggest Fall crimson). Each has MomentumRing + FormMeter for last 5 fights.
6. **Champions** — SectionHeader + horizontal strip of DataChip(champion) + HyperlinkLabel(name). EmptyState if no champs.
7. **Recent News** — SectionHeader + 5 NewsCards (full-width). "View all" hyperlink at bottom (no-op for now).

## New data queries
- 7-day cash history (sparkline) — query finance_transactions with running SUM(amount).
- Last-5-fights W/L for FormMeter — query fight_history for each watch-card fighter.
- Yesterday's cash (TrendIndicator previous) — finance_transactions cumulative up to yesterday.
- Roster delta (TrendIndicator previous) — fighters active 7 days ago.
- Champions delta (TrendIndicator previous) — held 7 days ago.

## Components used (of 24)
- Structural: Card, SectionHeader, DataChip, NewsCard, WatchCard, PortraitFrame, HyperlinkLabel, Button, EmptyState (9).
- Visual richness: GradientCard, TrendIndicator, FormMeter, MomentumRing, Sparkline, StatTile, GradientHeader (7).
- **Total: 16 of 24** (Card, SectionHeader, DataChip, NewsCard, WatchCard, PortraitFrame, HyperlinkLabel, Button, EmptyState + GradientCard, TrendIndicator, FormMeter, MomentumRing, Sparkline, StatTile, GradientHeader).

## Implementation notes
- Approach (a) destroy + recreate for refresh — simplest, refresh is infrequent.
- `_refresh_subtitle` updates the GradientHeader's subtitle via `set_subtitle()`.
- StatTile uses `current_value` + `previous_value` + `sparkline_data` to build its own TrendIndicator internally.
- WatchCard spec wraps in GradientCard (gold/crimson) instead of plain Accent card — gives the gradient hook.
- _render_watch_card signature is preserved (same args) but the body is rewritten to use GradientCard + MomentumRing + FormMeter.
- Defensive against missing data (e.g., no fight_history, no finance_transactions) — sparkline data falls back to `[cash]*7`, trend falls back to current=previous.
- The Dashboard is wrapped in CTkScrollableFrame (D5 — content can exceed viewport on small windows).

## Test plan
- Run `./run.sh test` (43 tests, 1 pre-existing failure expected per worklog → 42/43 pass).
- Run `python3 src/ui/widgets/components/_tests.py` (component smoke test).
- Smoke test dashboard instantiation in headless Xvfb against the live world DB:
  ```
  DISPLAY=:99 python3 -c "
  import customtkinter as ctk
  root = ctk.CTk(); root.withdraw()
  import sqlite3
  conn = sqlite3.connect('data/cage_empire.db', check_same_thread=False)
  from ui.state import GameState
  GameState._instance = None
  state = GameState(conn, player_promotion_id=1)
  from ui.screens.dashboard import DashboardScreen
  d = DashboardScreen(root)
  d._refresh()
  print('OK')"
  ```
- Profile refresh with `python3 scripts/perf/profile_refresh.py` to verify <500ms budget.

## Worklog entry
Appended to `/home/z/my-project/worklog.md` per the template.
