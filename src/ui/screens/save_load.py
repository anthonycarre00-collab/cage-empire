"""CAGE EMPIRE — Save/Load screen (Phase 1, Fix 1.3).

The Save/Load screen lets the player:
  - Save the current game under a player-chosen name.
  - See a list of every saved game (manual + auto-saves).
  - Load any saved game (overwriting the current DB).
  - Delete any saved game (both .db + .json).
  - Refresh the list.
  - Return to the Dashboard.

The screen is an Office-Mode screen (it is NOT a Fight Night screen —
the brief is explicit: "Save/Load is not a Fight Night screen"). It
reads `get_theme()` at every render so a theme switch live-updates
the colors + fonts.

Per docs/PHASE_1_PLAN.md §3 (Fix 1.3):
  - Office Mode default — uses `OFFICE` palette + Inter typography.
  - Registered with GameState as 'save_load'. The refresh callback
    re-queries list_saves() and re-renders the list.
  - Save name input — empty name → save_game(conn, None) which
    generates a timestamped name automatically.
  - Saves list — list_saves() returns dicts with keys: name,
    timestamp, sim_date, promotion, cash, fighters, events,
    schema_version, is_autosave, db_path. Sorted by timestamp DESC.
  - Load confirmation — `tkinter.messagebox.askokcancel` (CTk has
    no built-in message box; the stdlib one is fine).
  - Load reconnection — the screen closes the current conn, calls
    load_game(save_name) which returns a fresh conn, then updates
    BOTH `app.conn` AND `GameState.conn` (the app holds its own
    reference — see CageEmpireApp.__init__ line 133). Then calls
    `state.refresh_all()` + the app's top/bottom bar refreshers so
    every visible widget reflects the loaded state.
  - Delete confirmation — same dialog pattern.
  - Refresh button — re-queries list_saves() and re-renders.
  - Back button — `state.set_active_screen("dashboard")`.

CONVENTIONS compliance:
  §13 — Design Law: Investment pillar — the player's progress (the
        fighters they scouted, the champions they crowned, the
        market heat they built) is preserved across save/load.
        Without a Save/Load screen, every game session is ephemeral;
        with it, the player's empire is durable. The "remember that
        championship reign" storyline only matters if the player
        can come back to it tomorrow.
  §14 — Voice Layer: the screen displays sim_date (a date string),
        cash (game-state money, not a fighter attribute), fighter_
        count + event_count (game-state counts). These are all
        game-state values — explicitly OK to display as numbers per
        §14 (which forbids raw FIGHTER ATTRIBUTE values, not game
        state). No voice.py routing needed for save metadata.
  §15 — Event Bus: the screen does NOT publish events itself. Save
        calls save_load.save_game (a direct function call). Load
        calls save_load.load_game (a direct function call). The
        auto-save-on-TICK_ADVANCED subscriber is registered
        separately in CageEmpireApp.__init__ (Fix 1.2).

Architecture:
  - SaveLoadScreen(ctk.CTkFrame) — the screen widget
  - _build_save_section() — H2 title + name input + Save button
  - _build_saves_list() — H2 title + CTkScrollableFrame for rows
  - _build_actions() — Refresh + Back buttons
  - _on_save() — reads entry, calls save_game(conn, name),
                  clears entry, refreshes list, shows toast
  - _on_load(save_name) — confirms, closes conn, calls load_game,
                           updates app.conn + state.conn, refresh_all
  - _on_delete(save_name) — confirms, calls delete_save, refreshes
  - _refresh() — registered with GameState; re-renders the saves
                  list. Safe to call repeatedly (destroys old rows
                  first).
"""

import customtkinter as ctk
from tkinter import messagebox

from ui.theme import get_theme
from ui.state import get_state
from save_load import save_game, load_game, list_saves, delete_save


# ============================================================
# HELPERS
# ============================================================

def _format_cash(cash):
    """Format a cash value as $X.XM / $XK / $X,XXX.

    Matches the top bar's _update_top_bar formatting (src/ui/app.py
    lines 333-338) so the Save/Load screen displays cash consistently
    with the rest of the UI.
    """
    if cash is None:
        return "—"
    try:
        cash = float(cash)
    except (TypeError, ValueError):
        return "—"
    if abs(cash) >= 1_000_000:
        return f"${cash / 1_000_000:.1f}M"
    if abs(cash) >= 1_000:
        return f"${cash / 1_000:.0f}K"
    return f"${cash:,.0f}"


def _format_timestamp(ts):
    """Format an ISO timestamp ('2026-07-23T18:30:00') as a readable
    string ('2026-07-23 18:30').

    Falls back to the raw string if parsing fails (defensive — the
    timestamp comes from a JSON file the player could theoretically
    have edited).
    """
    if not ts:
        return ""
    # ISO format with seconds — strip the seconds for display.
    try:
        # datetime.fromisoformat handles 'YYYY-MM-DDTHH:MM:SS'
        from datetime import datetime
        dt = datetime.fromisoformat(str(ts))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(ts)


# ============================================================
# SCREEN
# ============================================================

class SaveLoadScreen(ctk.CTkFrame):
    """Save/Load screen — lets the player save, load, and delete games.

    Uses the dual-mode theme (Office Mode by default — Save/Load is
    not a Fight Night screen). Registered with GameState as
    'save_load'. The refresh callback (`_refresh`) re-queries
    `list_saves()` and re-renders the list.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Cache rendered save rows so we can destroy them on refresh.
        # _save_rows is a list of CTkFrame instances (one per save).
        self._save_rows = []

        # Build the three sections.
        self._build_save_section()
        self._build_saves_list()
        self._build_actions()

        # Initial render — populate the saves list.
        # Use after(50, ...) so the widget is fully laid out before
        # we query the filesystem (avoids a brief empty-flash on
        # first show). Safe — if the screen is destroyed before the
        # callback fires, _refresh's try/except handles it.
        self.after(50, self._refresh)

    # ============================================================
    # SECTION 1: SAVE INPUT
    # ============================================================

    def _build_save_section(self):
        """Build the 'Save Current Game' section.

        Layout:
          ┌─────────────────────────────────────────────────────┐
          │  SAVE / LOAD                                         │  ← H1
          ├─────────────────────────────────────────────────────┤
          │  Save Current Game                                   │  ← H2
          │  Save name: [____________________________] [Save]    │
          └─────────────────────────────────────────────────────┘
        """
        theme = get_theme()

        # H1 screen title
        title = ctk.CTkLabel(
            self, text="SAVE / LOAD",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=20, pady=(10, 15))

        # H2 panel title
        subtitle = ctk.CTkLabel(
            self, text="Save Current Game",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        subtitle.pack(side="top", fill="x", padx=20, pady=(0, 5))

        # Input row: label + entry + Save button
        input_row = ctk.CTkFrame(self, fg_color="transparent")
        input_row.pack(side="top", fill="x", padx=20, pady=(0, 15))

        name_label = ctk.CTkLabel(
            input_row, text="Save name:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
        )
        name_label.pack(side="left", padx=(0, 10))

        self.save_name_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="Enter a name (or leave blank for a timestamped save)",
            font=theme.fonts.body,
            height=32,
        )
        self.save_name_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.save_button = ctk.CTkButton(
            input_row, text="Save",
            font=theme.fonts.h3,
            width=100, height=32,
            corner_radius=6,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            command=self._on_save,
        )
        self.save_button.pack(side="left")

    # ============================================================
    # SECTION 2: SAVES LIST
    # ============================================================

    def _build_saves_list(self):
        """Build the 'Saved Games' section with a scrollable list.

        Layout:
          ┌─────────────────────────────────────────────────────┐
          │  Saved Games                                         │  ← H2
          │  ┌───────────────────────────────────────────────┐  │
          │  │ ★ Autosave — 2026-08-15      [Load] [Delete] │  │  ← row
          │  │   Alpha Combat · $12.4M · 4000 fighters      │  │
          │  ├───────────────────────────────────────────────┤  │
          │  │   My Save — 2026-08-10        [Load] [Delete] │  │
          │  │   Alpha Combat · $8.2M · 3950 fighters        │  │
          │  └───────────────────────────────────────────────┘  │
          └─────────────────────────────────────────────────────┘

        The list is rendered by _refresh() (called once on init via
        after(50, ...) and again whenever the screen is shown).
        """
        theme = get_theme()

        # H2 panel title
        subtitle = ctk.CTkLabel(
            self, text="Saved Games",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        subtitle.pack(side="top", fill="x", padx=20, pady=(0, 5))

        # Scrollable frame. Fixed height so the list scrolls within
        # the visible area rather than growing the screen indefinitely
        # (per the UI rules: max height with scroll overflow).
        self.saves_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.colors.bg_surface,
            corner_radius=8,
            height=400,
        )
        self.saves_scroll.pack(side="top", fill="both", expand=True,
                                padx=20, pady=(0, 15))

        # Empty-state label — shown when there are no saves. Hidden
        # when the list has at least one row. Kept as an attribute so
        # _refresh can show/hide it.
        self.empty_label = ctk.CTkLabel(
            self.saves_scroll,
            text="No saved games yet.\nSave your current game above, or play to trigger an auto-save (every 30 sim days).",
            font=theme.fonts.body,
            text_color=theme.colors.text_tertiary,
            justify="center",
        )
        self.empty_label.pack(fill="x", padx=20, pady=40)

    def _render_save_row(self, save):
        """Render a single save dict as a row in the scrollable frame.

        Args:
            save: dict from list_saves() with keys: name, timestamp,
                  sim_date, promotion, cash, fighters, events,
                  schema_version, is_autosave, db_path.

        Returns:
            The CTkFrame row instance (so _refresh can destroy it
            on the next refresh).
        """
        theme = get_theme()
        name = save.get("name", "?")
        is_autosave = bool(save.get("is_autosave"))
        timestamp = _format_timestamp(save.get("timestamp"))
        sim_date = save.get("sim_date") or "?"
        promotion = save.get("promotion") or "Unknown"
        cash = _format_cash(save.get("cash"))
        fighters = save.get("fighters")
        events = save.get("events")

        # Row container — bg_surface_elevated for autosaves (subtle
        # highlight), bg_surface for manual saves. This gives the
        # autosave a visual cue beyond just the ★ prefix.
        row_fg = (theme.colors.bg_surface_elevated
                   if is_autosave else theme.colors.bg_surface)
        row = ctk.CTkFrame(
            self.saves_scroll,
            fg_color=row_fg,
            corner_radius=6,
        )
        row.pack(fill="x", pady=2, padx=2)

        # Inner grid: name+date (col 0-1), metadata (col 0-1 row 1),
        # Load button (col 2), Delete button (col 3).
        # Use grid_columnconfigure(0, weight=1) so the labels expand
        # and the buttons stay right-aligned.
        row.grid_columnconfigure(0, weight=1)

        # Name (with ★ prefix for autosaves — gold color for the star)
        name_text = ("★ " + name) if is_autosave else name
        name_color = theme.colors.gold if is_autosave else theme.colors.text_primary
        name_label = ctk.CTkLabel(
            row, text=name_text,
            font=theme.fonts.h3, text_color=name_color,
            anchor="w",
        )
        name_label.grid(row=0, column=0, sticky="w", padx=10, pady=(6, 0))

        # Date (sim_date + wall-clock timestamp, right-aligned on row 0)
        date_text = sim_date
        if timestamp:
            date_text = f"{sim_date}  ·  {timestamp}"
        date_label = ctk.CTkLabel(
            row, text=date_text,
            font=theme.fonts.caption, text_color=theme.colors.text_tertiary,
            anchor="e",
        )
        date_label.grid(row=0, column=1, sticky="e", padx=10, pady=(6, 0))

        # Metadata (promotion · cash · fighter_count · event_count)
        meta_parts = [promotion, cash]
        if fighters is not None:
            meta_parts.append(f"{fighters:,} fighters")
        if events is not None:
            meta_parts.append(f"{events:,} events")
        meta_label = ctk.CTkLabel(
            row, text="  ·  ".join(meta_parts),
            font=theme.fonts.body_small, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        meta_label.grid(row=1, column=0, columnspan=2, sticky="w",
                         padx=10, pady=(0, 6))

        # Load button — gold accent, consistent with the Save button.
        load_btn = ctk.CTkButton(
            row, text="Load",
            font=theme.fonts.body_small,
            width=70, height=28,
            corner_radius=5,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            command=lambda n=name: self._on_load(n),
        )
        load_btn.grid(row=0, column=2, rowspan=2, padx=5, pady=5)

        # Delete button — danger red, signals destructive action.
        delete_btn = ctk.CTkButton(
            row, text="Delete",
            font=theme.fonts.body_small,
            width=70, height=28,
            corner_radius=5,
            fg_color=theme.colors.danger,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.text_primary,
            command=lambda n=name: self._on_delete(n),
        )
        delete_btn.grid(row=0, column=3, rowspan=2, padx=(0, 10), pady=5)

        return row

    # ============================================================
    # SECTION 3: ACTIONS (Refresh + Back)
    # ============================================================

    def _build_actions(self):
        """Build the Refresh + Back buttons at the bottom of the screen."""
        theme = get_theme()

        actions_row = ctk.CTkFrame(self, fg_color="transparent")
        actions_row.pack(side="top", fill="x", padx=20, pady=(0, 15))

        self.refresh_button = ctk.CTkButton(
            actions_row, text="↻ Refresh",
            font=theme.fonts.body,
            width=120, height=32,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._refresh,
        )
        self.refresh_button.pack(side="left", padx=(0, 10))

        self.back_button = ctk.CTkButton(
            actions_row, text="← Back to Dashboard",
            font=theme.fonts.body,
            width=180, height=32,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_back,
        )
        self.back_button.pack(side="left")

    # ============================================================
    # HANDLERS
    # ============================================================

    def _on_save(self):
        """Save the current game with the entered name.

        - Reads the entry value.
        - If empty, passes None to save_game (which generates a
          timestamped name like 'save_YYYYMMDD_HHMMSS').
        - Calls save_game(conn, name) — this writes
          data/saves/{name}.db + .json metadata.
        - Clears the entry.
        - Refreshes the list (so the new save appears at the top).
        - Shows a confirmation messagebox.

        Defensive — wrapped in try/except so a save failure (e.g.,
        disk full, permission denied) shows an error dialog instead
        of crashing the screen.
        """
        try:
            state = get_state()
            conn = state.get_conn()
            raw_name = self.save_name_entry.get().strip()
            # Pass None when empty — save_game handles it.
            save_name_arg = raw_name if raw_name else None
            actual_name = save_game(conn, save_name=save_name_arg)

            # Clear the entry.
            self.save_name_entry.delete(0, "end")

            # Refresh the list so the new save appears at the top.
            self._refresh()

            messagebox.showinfo(
                "Save Successful",
                f"Game saved as '{actual_name}'.\n\n"
                f"The save file is at data/saves/{actual_name}.db",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror(
                "Save Failed",
                f"Could not save the game:\n{type(e).__name__}: {e}",
                parent=self,
            )

    def _on_load(self, save_name):
        """Load a saved game. Confirms with the user first.

        CRITICAL — loading overwrites the active DB file. The player
        must confirm. After confirmation:
          1. Close the current conn (app.conn / state.conn — same
             object reference, but we close via state.conn).
          2. Call load_game(save_name) — this copies the save file
             back to data/cage_empire.db and returns a NEW conn.
          3. Update BOTH app.conn AND state.conn (the app holds its
             own reference — see CageEmpireApp.__init__ line 133).
          4. Call state.refresh_all() so every registered screen
             re-queries its data with the new conn.
          5. Refresh the app's top bar + bottom bar (they have their
             own conn-derived displays that aren't screens).

        Defensive — any failure during load shows an error dialog.
        If the conn was closed but load_game fails, we attempt to
        re-open a conn to the existing DB so the app stays usable.
        """
        # Confirm with the player — loading overwrites the current DB.
        confirm = messagebox.askokcancel(
            "Confirm Load",
            f"Load '{save_name}'?\n\n"
            f"This OVERWRITES your current game with the saved state. "
            f"Any unsaved progress will be lost.",
            parent=self,
        )
        if not confirm:
            return

        try:
            state = get_state()
            app = self.winfo_toplevel()

            # Close the current conn. Both app.conn and state.conn
            # reference the same object — closing via state.conn is
            # sufficient, but we also null out app.conn defensively.
            old_conn = state.get_conn()
            try:
                if old_conn is not None:
                    old_conn.close()
            except Exception:
                pass  # a broken close shouldn't block the load

            # load_game copies the save file to DB_PATH + returns a
            # NEW sqlite3.Connection (with PRAGMA foreign_keys = ON).
            new_conn = load_game(save_name)

            # Update BOTH references. The app holds its own conn
            # (separate from state.conn); both must point to the new
            # connection or the top bar will keep using the closed one.
            state.conn = new_conn
            if hasattr(app, "conn"):
                app.conn = new_conn

            # Refresh every registered screen + the app's top/bottom
            # bars. refresh_all() is the GameState method that calls
            # every screen's refresh callback.
            state.refresh_all()
            if hasattr(app, "_update_top_bar"):
                app._update_top_bar()
            if hasattr(app, "_update_bottom_bar"):
                app._update_bottom_bar()

            messagebox.showinfo(
                "Load Successful",
                f"Loaded '{save_name}'.\n\nThe game state has been restored.",
                parent=self,
            )
        except FileNotFoundError as e:
            messagebox.showerror(
                "Load Failed — Save Not Found",
                f"The save file for '{save_name}' could not be found.\n\n"
                f"It may have been moved or deleted.\n\n"
                f"Details: {e}",
                parent=self,
            )
            # Try to re-open a conn to the existing DB so the app
            # stays usable (the old conn was closed above).
            self._recover_conn()
        except Exception as e:
            messagebox.showerror(
                "Load Failed",
                f"Could not load '{save_name}':\n"
                f"{type(e).__name__}: {e}",
                parent=self,
            )
            self._recover_conn()

    def _recover_conn(self):
        """Best-effort recovery — re-open a conn to the current DB.

        Called from _on_load's exception handlers when the old conn
        was closed but load_game failed. Without this, the app would
        be stuck with a closed conn and every subsequent operation
        would crash.
        """
        try:
            import sqlite3
            from pathlib import Path
            state = get_state()
            app = self.winfo_toplevel()
            # Default DB path (matches CageEmpireApp.__init__).
            db_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "cage_empire.db"
            if hasattr(app, "db_path") and app.db_path:
                db_path = app.db_path
            new_conn = sqlite3.connect(str(db_path))
            new_conn.execute("PRAGMA foreign_keys = ON;")
            state.conn = new_conn
            if hasattr(app, "conn"):
                app.conn = new_conn
        except Exception as e:
            print(f"Warning: _recover_conn failed: {e}", flush=True)

    def _on_delete(self, save_name):
        """Delete a saved game. Confirms with the user first.

        Calls delete_save(save_name) which removes both the .db and
        .json files. Returns True if anything was deleted. We then
        refresh the list so the row disappears.
        """
        # Confirm — deletion is permanent.
        confirm = messagebox.askokcancel(
            "Confirm Delete",
            f"Delete '{save_name}'?\n\n"
            f"This PERMANENTLY removes the save file. This cannot be undone.",
            parent=self,
        )
        if not confirm:
            return

        try:
            deleted = delete_save(save_name)
            if deleted:
                self._refresh()
                messagebox.showinfo(
                    "Delete Successful",
                    f"Save '{save_name}' has been deleted.",
                    parent=self,
                )
            else:
                messagebox.showwarning(
                    "Nothing to Delete",
                    f"No save file found for '{save_name}'. "
                    f"It may have already been removed. Refreshing the list.",
                    parent=self,
                )
                self._refresh()
        except Exception as e:
            messagebox.showerror(
                "Delete Failed",
                f"Could not delete '{save_name}':\n"
                f"{type(e).__name__}: {e}",
                parent=self,
            )

    def _on_back(self):
        """Navigate back to the Dashboard."""
        try:
            get_state().set_active_screen("dashboard")
        except Exception as e:
            print(f"Warning: navigation to dashboard failed: {e}",
                  flush=True)

    # ============================================================
    # REFRESH CALLBACK (registered with GameState)
    # ============================================================

    def _refresh(self):
        """Refresh callback — re-query list_saves() and re-render.

        Registered with GameState as this screen's refresh callback.
        Called:
          - Once on init (via after(50, ...)).
          - On every navigation to this screen (set_active_screen
            triggers state.refresh(name)).
          - On refresh_all() (after Advance Day, Save, Load, theme
            toggle).
          - When the player clicks the Refresh button.

        Safe to call repeatedly — destroys the old rows before
        rendering the new ones. Defensive against filesystem errors
        (if list_saves throws, the empty-state label is shown).
        """
        try:
            # Destroy the old rows.
            for row in self._save_rows:
                try:
                    row.destroy()
                except Exception:
                    pass
            self._save_rows = []

            # Query the saves list.
            saves = list_saves()

            if not saves:
                # Show the empty-state label.
                try:
                    self.empty_label.pack(fill="x", padx=20, pady=40)
                except Exception:
                    pass
                return

            # Hide the empty-state label.
            try:
                self.empty_label.pack_forget()
            except Exception:
                pass

            # Render each save as a row.
            for save in saves:
                try:
                    row = self._render_save_row(save)
                    self._save_rows.append(row)
                except Exception as e:
                    print(f"Warning: failed to render save row "
                          f"'{save.get('name', '?')}': {e}", flush=True)
        except Exception as e:
            print(f"Warning: SaveLoadScreen._refresh failed: {e}",
                  flush=True)
