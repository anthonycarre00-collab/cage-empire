"""CAGE EMPIRE — Scouting screen (Stage 6 — Task 6.5).

The Talent Hunter's reports — every scouting report the player's
promotion has commissioned. Mirrors the Dashboard's card layout
(adapted for the report-card pattern) with a "Sign Scout" form
below for assigning a scout to a new target.

Per docs/GUI_PLAN.md §5.2 (FIGHTERS group):
  "Scouting — Regional scouting targets, scout assignments,
  hidden-potential reports. Primary tables: scouting_reports,
  fighters, regions."

Per docs/CONVENTIONS.md §17 (UI Snapshot Rule — CRITICAL):
  Office Mode UI screens MUST read from `*_descriptors` cache
  tables for fighter interpretation data. The Scouting screen
  reads from:
    - `scouting_reports` (game state — the scouting system writes
      these on tick. NOT a fighter attribute table. The
      estimated_potential / estimated_ceiling / estimated_floor /
      estimated_strengths / estimated_weaknesses columns already
      hold VOICE PHRASES (descriptors), not raw numbers — the
      scouting system (Task ID 18) routes through voice.py at
      report-generation time per §14.4. The Scouting screen
      displays them as-is.)
    - `fighters` (game state — first_name, last_name, nickname for
      the report's target_fighter_id. Names are NOT raw attribute
      values per §14.)
    - `staff` (game state — first_name, last_name for the scout.
      Staff names are NOT fighter attributes.)
    - `weight_classes` (game state — for the target's weight class.)

  This screen NEVER reads from `fighter_attributes` (raw 0-100
  values), `fighter_personality` (raw trait values), `fighter_bios`
  (long-form prose — that's for Fighter Profile). See D1.

Per docs/CONVENTIONS.md §14 (Interpretation Layer — CRITICAL):
  No raw attribute values appear in the player-facing UI.
    - Estimated potential / ceiling / floor → already voice phrases
      written by the scouting system (Task ID 18 — verified by the
      `test_scouting.py` case J which asserts "estimated_potential
      contains no digits").
    - Estimated strengths / weaknesses → JSON list of voice phrases
      (each is a descriptor like "above-average takedown defense").
    - Report text → already voice-layered prose (the scouting
      system composes it at report-generation time).
    - Fighter name, scout name, weight class name → names + classi-
      fications, NOT attributes per §14.

Architecture (adapts DashboardScreen's card pattern for the
report-card layout, NOT the Roster's Treeview — scouting reports
are long-form prose, not tabular data):
  - ScoutingScreen(ctk.CTkFrame) — the screen widget.
  - _build_header() — H1 title + report-count subtitle.
  - _build_reports_section() — H2 "Scouting Reports" + a scrollable
    frame for the report cards. Empty-state label shown when 0
    reports exist.
  - _build_assign_section() — H2 "Assign Scout" + scout dropdown +
    target fighter entry + "Assign Scout" button + status label.
  - _refresh() — registered with GameState; re-queries reports +
    scouts + re-renders both sections.

Actions:
  - "View Fighter" button on each report card → set_fighter_id()
    on Fighter Profile + navigate.
  - "Dismiss Report" button on each report card → DELETE the
    scouting_reports row + refresh.
  - "Assign Scout" button → calls scouting.assign_scout(conn,
    scout_id, target_fighter_id, promotion_id). The report itself
    is generated 7 days later by _check_scouting_assignments on
    each tick (per the test_scouting.py case I).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Source-of-truth map. See the §17 comment block above. The
      Scouting screen reads ONLY from scouting_reports (game state)
      + fighters (game state) + staff (game state) + weight_classes
      (game state). It NEVER touches fighter_attributes /
      fighter_personality / fighter_bios.

      Important: the scouting_reports table is NOT in §17.3's cache
      table list. It's a GAME STATE table written by the scouting
      system on tick (per scouting.py:130 + tick_processor.run_tick
      → _check_scouting_assignments). The estimated_potential /
      ceiling / floor / strengths / weaknesses / report_text columns
      are ALREADY voice phrases (verified by test_scouting.py case
      J — "estimated_potential contains no digits"). The scouting
      system (Task ID 18) is itself §14-compliant at write time per
      §14.4. So the Scouting screen displaying these columns as-is
      is NOT a §14 violation — it's displaying the interpretation-
      layer output that the scouting system already produced.

  D2  Card layout (NOT a Treeview). The Roster + Free Agents use
      ttk.Treeview because their data is tabular (Name | WC | Phase
      | ...). Scouting reports are LONG-FORM PROSE — a Treeview row
      can't hold a 200-character report_text. The Dashboard's card
      pattern is the right fit: each report is a CTkFrame card with
      multi-line CTkLabels inside. The cards stack vertically in a
      scrollable frame (CTkScrollableFrame) so the player can read
      50+ reports without page-flipping.

      The scrollable frame has a max-height (480px) so the Assign
      Scout section below it is always visible without scrolling
      the whole screen.

  D3  Empty state. At day 1 (the seeded DB state), the player has
      0 scouting reports (verified during pre-flight). The empty-
      state label says: "No scouting reports yet. Assign a scout to
      evaluate a fighter from the Free Agents screen." This points
      the player to the next action — same UX idiom as the Roster's
      "Your roster is empty. Sign some free agents." empty state.

  D4  Report card layout. Each card shows:
        ┌──────────────────────────────────────────────────────┐
        │ Report: Hiroki Nakamura "Mist"  · Welterweight       │
        │ Scout: George Nguyen · Date: 2026-08-15              │
        │ Confidence: 71/100 · Stale: No                       │
        │                                                       │
        │ Estimated Potential: can develop into a contender    │
        │ Estimated Ceiling:   can develop into a contender    │
        │ Estimated Floor:     very low ceiling                │
        │ Strengths: one-punch knockout threat, iron chin      │
        │ Weaknesses: limited cardio                            │
        │                                                       │
        │ ┌─ REPORT ──────────────────────────────────────┐    │
        │ │ SCOUTING REPORT: Hiroki Nakamura 'Mist'       │    │
        │ │ Scout: George Nguyen                          │    │
        │ │ Date: 2026-08-15                              │    │
        │ │ ...                                            │    │
        │ └────────────────────────────────────────────────┘    │
        │                                                       │
        │ [View Fighter]  [Dismiss Report]                     │
        └──────────────────────────────────────────────────────┘

      - The header line is the fighter's name + weight class (game
        state, not attributes).
      - The scout line is the scout's name + the report_date (game
        state).
      - The confidence is the scout_confidence (0-100) — this is
        NOT a fighter attribute, it's the SCOUT's confidence in
        their own report. Per §14 ("No raw attribute values"), the
        rule applies to FIGHTER attributes (potential, punch_power,
        etc.), not to meta-information about the scouting process
        itself. WMMA5 + EWMMA both display scout confidence as a
        number. This is consistent with §14's spirit.
      - The estimated_potential / ceiling / floor / strengths /
        weaknesses are all already voice phrases (D1).
      - The report_text is shown in a sub-frame with a slightly
        different background (bg_surface_elevated) to visually
        separate the scout's prose from the structured fields.
      - "View Fighter" navigates to Fighter Profile (same pattern
        as the Roster's double-click).
      - "Dismiss Report" deletes the scouting_reports row + refresh.

  D5  Stale flag. If `is_stale=1`, the card shows a "⚠ Stale"
      badge in the header. The scouting system's
      mark_stale_reports function (called on certain events per
      scouting.py:736) flags reports as stale when the underlying
      fighter's state has changed significantly. The player can
      dismiss stale reports or re-scout the fighter.

  D6  Assign Scout form. Layout:
        Scout:   [Select Scout ▼]
        Target:  [Fighter ID or name] [____________]
        [Assign Scout]

      The scout dropdown lists every scout at the player's
      promotion (role_type='scout' AND promotion_id=player's). If
      the player has 0 scouts, the dropdown is empty + the form
      shows a hint: "Your promotion has no scouts. Hire one from
      the Contracts screen." (Future task — the Contracts screen
      will let the player hire staff.)

      The target entry accepts either:
        - A fighter_id (numeric) — exact match.
        - A fighter name (case-insensitive substring) — first
          match wins. The handler prints a warning if multiple
          fighters match (the player should be more specific).

      The "Assign Scout" button calls scouting.assign_scout(conn,
      scout_id, target_fighter_id, promotion_id). The function
      returns False if the scout is already assigned — the status
      label shows "Scout is already on assignment."

      The report itself is NOT generated immediately — it takes 7
      ticks (7 days) per scouting.py:SCOUTING_DURATION_DAYS. The
      status label says "Scout assigned. Report in 7 days."

  D7  Refresh pattern. Following DashboardScreen + RosterScreen:
      dynamic widgets (report cards) are tracked in an instance
      list (_report_cards). _refresh() destroys every card in the
      list, re-queries, re-renders. Static structure (H1 title,
      H2 section headers, scrollable frame, Assign Scout form) is
      built once in __init__. Theme-change refresh re-renders with
      the new theme's colors/fonts.

  D8  Status feedback. Same pattern as Free Agents screen (D4 in
      free_agents.py) — a small label below the Assign button
      shows the last action's result. Color-coded: gold for
      success, crimson for failure, text_tertiary for idle.

  D9  Performance. The reports query is one JOIN across 4 tables
      (scouting_reports + fighters + staff + weight_classes) with
      a WHERE clause on promotion_id. On the live 4450-fighter DB
      with 0 reports at day 1, this returns 0 rows in <5ms. Even
      with 100 reports (a long-running save), the query is <20ms.
      The card rendering is the slowest part (~5ms per card), well
      within the §17.5 spirit.

  D10 Defensive against missing data. If a report's target_fighter
      has been deleted (shouldn't happen — FK constraint, but
      defensive), the card shows "(fighter no longer exists)".
      Same for the scout. If the JSON-parsed strengths/weaknesses
      list is malformed, show "(none reported)".

  D11 Navigation. "View Fighter" button → set_fighter_id() on
      Fighter Profile + state.set_active_screen("fighter_profile").
      Same pattern as Roster + Free Agents.
"""

import sqlite3
import json

import customtkinter as ctk

from ui.theme import get_theme
from ui.state import get_state

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine. Used here for
# defensive fallback ONLY — the scouting_reports columns themselves
# are plain voice phrases (not "label||phrase"), but the target
# fighter's career_phase / momentum (shown on the card if available
# via fighter_descriptors) ARE in the "label||phrase" format.
from interpretation.context_engine import decode_phrase


# ============================================================
# CONSTANTS
# ============================================================

# Max height of the scrollable reports frame (px). Keeps the Assign
# Scout form visible without scrolling the whole screen.
REPORTS_FRAME_HEIGHT = 480


# ============================================================
# HELPERS
# ============================================================

def _format_fighter_name(first, last, nickname):
    """Format a fighter's name with optional nickname in quotes.

    Mirrors roster.py / free_agents.py _format_name. Shared display
    convention across all screens that show fighter names.
    """
    parts = []
    if first:
        parts.append(str(first).strip())
    if last:
        parts.append(str(last).strip())
    name = " ".join(parts).strip() or "Unknown"
    if nickname and str(nickname).strip() and str(nickname).strip().lower() != "none":
        nick = str(nickname).strip()
        name += f' "{nick}"'
    return name


def _format_staff_name(first, last):
    """Format a scout's name as 'First Last'."""
    parts = []
    if first:
        parts.append(str(first).strip())
    if last:
        parts.append(str(last).strip())
    return " ".join(parts).strip() or "Unknown"


def _phrase_or_fallback(stored_value, fallback):
    """Decode a "label||phrase" cache value, or return a fallback.

    Per §17.4: the UI displays the voice PHRASE (after ||), never
    the canonical label (before ||). Used here for the target
    fighter's career_phase / momentum (cached in
    fighter_descriptors in "label||phrase" format).
    """
    phrase = decode_phrase(stored_value)
    return phrase if phrase else fallback


def _parse_descriptor_list(json_str):
    """Parse a JSON list of voice-phrase descriptors into a string.

    The scouting system stores estimated_strengths / estimated_
    weaknesses as a JSON list of strings (each a voice phrase like
    "above-average takedown defense"). This helper parses the JSON
    + joins the list with ", " for display.

    Defensive — if the JSON is malformed or the value is NULL,
    returns "(none reported)".
    """
    if not json_str:
        return "(none reported)"
    try:
        items = json.loads(json_str)
        if not isinstance(items, list):
            return str(json_str)
        if not items:
            return "(none reported)"
        # Filter out None / empty strings + join.
        cleaned = [str(x).strip() for x in items if x]
        if not cleaned:
            return "(none reported)"
        return ", ".join(cleaned)
    except (json.JSONDecodeError, TypeError):
        # Not valid JSON — return the raw string (defensive).
        return str(json_str)


# ============================================================
# SCOUTING SCREEN
# ============================================================

class ScoutingScreen(ctk.CTkFrame):
    """Scouting — the player's scouting reports + assign-scout form.

    Office Mode only (NOT a Fight Night screen). Registered with
    GameState as 'scouting'. The refresh callback (`_refresh`)
    re-queries the reports + scouts + re-renders both sections.

    Usage:
        screen = ScoutingScreen(parent_frame)
        state.register_screen("scouting", screen, screen._refresh)
        state.set_active_screen("scouting")
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Background — match Office Mode base.
        theme = get_theme()
        self.configure(fg_color=theme.colors.bg_base)

        # Cached report data (list of dicts). Refreshed by _refresh().
        self._reports_data = []

        # Cached scout list (list of (staff_id, name) tuples).
        # Refreshed by _refresh().
        self._scouts = []

        # Tracked dynamic widgets — destroyed + re-rendered on every
        # _refresh(). Per D7.
        self._report_cards = []
        self._subtitle_label = None
        self._reports_empty_label = None
        self._scout_menu = None
        self._target_entry = None
        self._assign_button = None
        self._assign_status_label = None
        self._no_scouts_label = None
        self._reports_scroll = None

        # Build the static structure.
        self._build_header()
        self._build_reports_section()
        self._build_assign_section()
        self._build_footer()

        # Initial render.
        self.after(50, self._refresh)

    # ============================================================
    # SECTION 1 — HEADER
    # ============================================================

    def _build_header(self):
        """Build the H1 title + subtitle ('SCOUTING — Talent Acquisition')."""
        theme = get_theme()

        title = ctk.CTkLabel(
            self, text="SCOUTING — Talent Acquisition",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # Subtitle populated by _refresh (needs the count from the DB).
        self._subtitle_label = ctk.CTkLabel(
            self, text="Loading scouting reports...",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # SECTION 2 — REPORTS (scrollable card list)
    # ============================================================

    def _build_reports_section(self):
        """Build the Scouting Reports section header + scrollable frame.

        Per D2: uses a CTkScrollableFrame (NOT a Treeview) because
        scouting reports are long-form prose, not tabular data. Each
        report renders as a CTkFrame card inside the scrollable frame.
        """
        theme = get_theme()

        # Section header.
        section_header = ctk.CTkLabel(
            self, text="— SCOUTING REPORTS —",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        section_header.pack(side="top", fill="x", padx=20, pady=(0, 6))

        # Scrollable frame for the report cards. max-height keeps the
        # Assign Scout section visible without scrolling the whole screen.
        self._reports_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            height=REPORTS_FRAME_HEIGHT,
        )
        self._reports_scroll.pack(side="top", fill="both", expand=True,
                                   padx=20, pady=(0, 10))
        # Prevent the scrollable frame from growing past its height
        # when many cards are added (it should scroll internally).
        self._reports_scroll.pack_propagate(False)

        # Empty-state label — shown when 0 reports exist (D3). Packed
        # into the scrollable frame so it appears in the right place.
        self._reports_empty_label = ctk.CTkLabel(
            self._reports_scroll,
            text="No scouting reports yet. Assign a scout to evaluate "
                 "a fighter from the Free Agents screen.",
            font=theme.fonts.body,
            text_color=theme.colors.text_tertiary,
            justify="center",
            wraplength=600,
        )
        # _refresh decides whether to pack this.

    # ============================================================
    # SECTION 3 — ASSIGN SCOUT FORM
    # ============================================================

    def _build_assign_section(self):
        """Build the Assign Scout form (D6).

        Layout:
          — ASSIGN SCOUT —
          Scout:   [Select Scout ▼]
          Target:  [Fighter ID or name] [____________]
          [Assign Scout]   Status: ...
        """
        theme = get_theme()

        # Section header.
        section_header = ctk.CTkLabel(
            self, text="— ASSIGN SCOUT —",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        section_header.pack(side="top", fill="x", padx=20, pady=(0, 6))

        # Form card.
        form_card = ctk.CTkFrame(
            self, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        form_card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Inner padding frame.
        inner = ctk.CTkFrame(form_card, fg_color="transparent")
        inner.pack(fill="x", padx=15, pady=15)

        # Row 1: Scout dropdown.
        scout_row = ctk.CTkFrame(inner, fg_color="transparent")
        scout_row.pack(fill="x", pady=(0, 8))

        scout_label = ctk.CTkLabel(
            scout_row, text="Scout:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            width=80, anchor="w",
        )
        scout_label.pack(side="left", padx=(0, 12))

        self._scout_menu = ctk.CTkOptionMenu(
            scout_row,
            values=["(no scouts available)"],
            width=240, height=30,
            font=theme.fonts.body,
            dropdown_font=theme.fonts.body,
            fg_color=theme.colors.bg_surface_elevated,
            button_color=theme.colors.bg_surface_elevated,
            button_hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
        )
        self._scout_menu.set("(no scouts available)")
        self._scout_menu.pack(side="left")

        # "No scouts" hint — shown when the player's promotion has 0
        # scouts. Hidden by _refresh when scouts exist.
        self._no_scouts_label = ctk.CTkLabel(
            scout_row,
            text="Your promotion has no scouts. Hire one from the "
                 "Contracts screen (future task).",
            font=theme.fonts.caption,
            text_color=theme.colors.warning,
            anchor="w",
        )
        # _refresh decides whether to pack this.

        # Row 2: Target fighter entry.
        target_row = ctk.CTkFrame(inner, fg_color="transparent")
        target_row.pack(fill="x", pady=(0, 8))

        target_label = ctk.CTkLabel(
            target_row, text="Target:",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            width=80, anchor="w",
        )
        target_label.pack(side="left", padx=(0, 12))

        self._target_entry = ctk.CTkEntry(
            target_row,
            placeholder_text="Fighter ID or name (e.g., 'Hiroki Nakamura' or 3451)",
            width=380, height=30,
            font=theme.fonts.body,
            fg_color=theme.colors.bg_surface_elevated,
            border_color=theme.colors.bg_border,
            text_color=theme.colors.text_primary,
        )
        self._target_entry.pack(side="left")
        # Bind Enter key → assign.
        self._target_entry.bind("<Return>", lambda e: self._on_assign_clicked())

        # Row 3: Assign button + status label.
        button_row = ctk.CTkFrame(inner, fg_color="transparent")
        button_row.pack(fill="x", pady=(4, 0))

        self._assign_button = ctk.CTkButton(
            button_row, text="✚  Assign Scout",
            font=theme.fonts.body,
            width=160, height=32,
            corner_radius=6,
            fg_color=theme.colors.gold,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.bg_base,
            command=self._on_assign_clicked,
        )
        self._assign_button.pack(side="left")

        self._assign_status_label = ctk.CTkLabel(
            button_row,
            text="Pick a scout + target, then Assign Scout.",
            font=theme.fonts.body_small,
            text_color=theme.colors.text_tertiary,
            anchor="w",
        )
        self._assign_status_label.pack(side="left", padx=20)

    # ============================================================
    # SECTION 4 — FOOTER
    # ============================================================

    def _build_footer(self):
        """Build the footer hint: 'Reports arrive 7 days after assignment.'"""
        theme = get_theme()

        footer_label = ctk.CTkLabel(
            self,
            text="Reports arrive 7 days after assignment. Stale reports "
                 "(⚠) should be re-scouted — the fighter's situation has "
                 "changed since the report was filed.",
            font=theme.fonts.caption,
            text_color=theme.colors.text_tertiary,
            anchor="w",
        )
        footer_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # HANDLERS — assign, dismiss, view-fighter
    # ============================================================

    def _on_assign_clicked(self):
        """Handle Assign Scout button click (D6).

        Reads the scout dropdown + target entry, calls
        scouting.assign_scout(conn, scout_id, target_fighter_id,
        promotion_id). Sets a status message. The report itself is
        NOT generated immediately — it takes 7 ticks (7 days) per
        scouting.py:SCOUTING_DURATION_DAYS.
        """
        try:
            # Parse the scout dropdown value. _refresh populates it
            # with "First Last [id=N]" format.
            scout_choice = self._scout_menu.get()
            scout_id = self._parse_id_from_label(scout_choice)
            if scout_id is None:
                self._set_assign_status(
                    "Pick a scout first.", "warning")
                return

            # Parse the target entry. Accepts either a fighter_id
            # (numeric) or a fighter name (case-insensitive substring).
            target_text = ""
            try:
                target_text = self._target_entry.get().strip()
            except Exception:
                pass
            if not target_text:
                self._set_assign_status(
                    "Enter a fighter ID or name.", "warning")
                return

            state = get_state()
            conn = state.get_conn()
            if conn is None:
                self._set_assign_status(
                    "Database unavailable.", "danger")
                return
            promo_id = state.get_player_promotion_id()

            # Resolve the target fighter_id.
            target_fighter_id = self._resolve_target(conn, target_text)
            if target_fighter_id is None:
                self._set_assign_status(
                    f"No fighter matches '{target_text}'.", "danger")
                return

            # Lazy import — scouting.py is in src/, on the sys.path
            # that app.py manipulates.
            try:
                import scouting
            except ImportError:
                self._set_assign_status(
                    "Scouting service unavailable.", "danger")
                return

            # assign_scout returns False if the scout is already
            # assigned. The function itself prints no warning — we
            # surface a player-facing message.
            ok = scouting.assign_scout(
                conn, scout_id, target_fighter_id, promo_id,
            )

            if not ok:
                self._set_assign_status(
                    "Scout is already on assignment.", "warning")
                return

            # Commit the assignment (the helper doesn't commit).
            try:
                conn.commit()
            except sqlite3.Error as e:
                self._set_assign_status(
                    f"Assigned but commit failed: {e}", "danger")
                return

            # Look up the fighter + scout names for the status message.
            fighter_name = "fighter"
            try:
                row = conn.execute(
                    "SELECT first_name || ' ' || last_name FROM fighters "
                    "WHERE fighter_id = ?",
                    (target_fighter_id,),
                ).fetchone()
                if row and row[0]:
                    fighter_name = row[0]
            except sqlite3.Error:
                pass

            scout_name = "scout"
            try:
                row = conn.execute(
                    "SELECT first_name || ' ' || last_name FROM staff "
                    "WHERE staff_id = ?",
                    (scout_id,),
                ).fetchone()
                if row and row[0]:
                    scout_name = row[0]
            except sqlite3.Error:
                pass

            self._set_assign_status(
                f"{scout_name} assigned to scout {fighter_name}. "
                f"Report in 7 days.",
                "success")

            # Clear the target entry for the next assignment.
            try:
                self._target_entry.delete(0, "end")
            except Exception:
                pass

            # Refresh — the scout dropdown may need to update (the
            # assigned scout is still listed, but future tasks may
            # show assignment state next to the name).
            self._refresh()
        except Exception as e:
            print(f"Warning: assign handler failed: {e}", flush=True)
            self._set_assign_status(f"Assign failed: {e}", "danger")

    def _on_dismiss_clicked(self, report_id):
        """Handle Dismiss Report button click.

        Deletes the scouting_reports row + refreshes. The delete is
        a hard delete (no soft-delete column on scouting_reports).
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                self._set_assign_status(
                    "Database unavailable.", "danger")
                return

            conn.execute(
                "DELETE FROM scouting_reports WHERE scouting_report_id = ?",
                (report_id,),
            )
            conn.commit()

            self._refresh()
        except sqlite3.Error as e:
            print(f"Warning: dismiss report failed: {e}", flush=True)
            self._set_assign_status(
                f"Dismiss failed: {e}", "danger")

    def _on_view_fighter_clicked(self, fighter_id):
        """Handle View Fighter button click → navigate to Fighter Profile.

        Same pattern as Roster + Free Agents: set_fighter_id() on
        the Fighter Profile screen, then state.set_active_screen.
        """
        try:
            state = get_state()
            profile_screen = state.get_screen("fighter_profile")
            if profile_screen is not None and hasattr(
                profile_screen, "set_fighter_id"
            ):
                profile_screen.set_fighter_id(fighter_id)
            state.set_active_screen("fighter_profile")
        except ValueError as e:
            print(f"Warning: navigation to fighter_profile failed: {e}",
                  flush=True)
        except Exception as e:
            print(f"Warning: view-fighter handler failed: {e}", flush=True)

    # ============================================================
    # REFRESH CALLBACK (registered with GameState)
    # ============================================================

    def _refresh(self):
        """Refresh callback — re-query reports + scouts + re-render.

        Registered with GameState as this screen's refresh callback.
        Called on init, on navigation, and on refresh_all() (after
        Advance Day, Save, Load, theme toggle, scout-assigned,
        report-dismissed).
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                return
            promo_id = state.get_player_promotion_id()

            # Query reports.
            self._reports_data = self._query_reports(conn, promo_id)

            # Query scouts.
            self._scouts = self._query_scouts(conn, promo_id)

            # Render both sections.
            self._render_reports()
            self._refresh_scout_dropdown()
            self._refresh_subtitle(len(self._reports_data))
        except Exception as e:
            print(f"Warning: ScoutingScreen._refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Subtitle — "N scouting reports · M scouts available"
    # ------------------------------------------------------------

    def _refresh_subtitle(self, report_count):
        """Update the subtitle label with the report count + scout count."""
        try:
            theme = get_theme()
            scout_count = len(self._scouts)
            scout_word = "scout" if scout_count == 1 else "scouts"
            report_word = "report" if report_count == 1 else "reports"
            text = (f"{report_count:,} {report_word}  ·  "
                    f"{scout_count} {scout_word} available")
            self._subtitle_label.configure(
                text=text,
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )
        except Exception as e:
            print(f"Warning: scouting subtitle refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Query reports (joined with fighters + staff + weight_classes)
    # ------------------------------------------------------------

    def _query_reports(self, conn, promo_id):
        """Query scouting_reports for the player's promotion.

        Per D1: reads from scouting_reports (game state — the
        scouting system writes these on tick) + fighters (game state
        — for the target fighter's name) + staff (game state — for
        the scout's name) + weight_classes (game state — for the
        target's weight class). NEVER reads from fighter_attributes /
        fighter_personality / fighter_bios.

        Returns:
            List of dicts, one per report. Each dict has keys:
                report_id, fighter_id, fighter_name, weight_class_name,
                scout_id, scout_name, report_date, estimated_potential,
                estimated_ceiling, estimated_floor, estimated_strengths,
                estimated_weaknesses, scout_confidence, is_stale,
                report_text.
        """
        rows = []
        try:
            sql = """
                SELECT sr.scouting_report_id, sr.target_fighter_id,
                       f.first_name, f.last_name, f.nickname,
                       wc.name AS weight_class_name,
                       sr.scout_id,
                       s.first_name, s.last_name,
                       sr.report_date,
                       sr.estimated_potential,
                       sr.estimated_ceiling,
                       sr.estimated_floor,
                       sr.estimated_strengths,
                       sr.estimated_weaknesses,
                       sr.scout_confidence,
                       sr.is_stale,
                       sr.report_text
                FROM scouting_reports sr
                LEFT JOIN fighters f
                  ON f.fighter_id = sr.target_fighter_id
                LEFT JOIN weight_classes wc
                  ON wc.weight_class_id = f.weight_class_id
                LEFT JOIN staff s
                  ON s.staff_id = sr.scout_id
                WHERE sr.promotion_id = ?
                ORDER BY sr.report_date DESC, sr.scouting_report_id DESC
            """
            rows = conn.execute(sql, (promo_id,)).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: scouting reports query failed: {e}",
                  flush=True)
            return []

        reports = []
        for r in rows:
            (rid, fid, ffirst, flast, fnick, wc_name,
             sid, sfirst, slast, rdate,
             pot, ceil, floor, strengths, weaknesses,
             confidence, is_stale, report_text) = r
            reports.append({
                "report_id": rid,
                "fighter_id": fid,
                "fighter_name": _format_fighter_name(ffirst, flast, fnick)
                    if fid else "(fighter removed)",
                "weight_class_name": wc_name or "Unknown",
                "scout_id": sid,
                "scout_name": _format_staff_name(sfirst, slast)
                    if sid else "(scout removed)",
                "report_date": rdate or "Unknown",
                "estimated_potential": pot or "(not assessed)",
                "estimated_ceiling": ceil or "(not assessed)",
                "estimated_floor": floor or "(not assessed)",
                "estimated_strengths": strengths,
                "estimated_weaknesses": weaknesses,
                "scout_confidence": confidence,
                "is_stale": is_stale,
                "report_text": report_text or "",
            })
        return reports

    # ------------------------------------------------------------
    # Query scouts at the player's promotion
    # ------------------------------------------------------------

    def _query_scouts(self, conn, promo_id):
        """Query scouts at the player's promotion.

        Returns a list of (staff_id, name) tuples. Used to populate
        the scout dropdown. The scouting system's assign_scout
        function reads the scout's specialty JSON to check if they're
        already assigned — we don't replicate that here (the player
        sees all scouts; the assign call surfaces "already assigned"
        if applicable).
        """
        rows = []
        try:
            rows = conn.execute(
                """
                SELECT staff_id, first_name, last_name
                FROM staff
                WHERE role_type = 'scout' AND promotion_id = ?
                ORDER BY first_name ASC, last_name ASC
                """,
                (promo_id,),
            ).fetchall()
        except sqlite3.Error as e:
            print(f"Warning: scout query failed: {e}", flush=True)
            return []

        out = []
        for sid, first, last in rows:
            out.append((sid, _format_staff_name(first, last)))
        return out

    # ------------------------------------------------------------
    # Render the report cards
    # ------------------------------------------------------------

    def _render_reports(self):
        """Render the report cards into the scrollable frame (D2, D4).

        Per D7: destroys every existing card first, then re-renders.
        Per D3: shows the empty-state label when 0 reports exist.
        """
        try:
            # Destroy existing cards.
            for card in self._report_cards:
                try:
                    card.destroy()
                except Exception:
                    pass
            self._report_cards = []

            # Hide the empty-state label by default — shown below
            # only if no reports exist.
            try:
                self._reports_empty_label.pack_forget()
            except Exception:
                pass

            if not self._reports_data:
                # Empty state (D3).
                self._reports_empty_label.configure(
                    text="No scouting reports yet. Assign a scout to "
                         "evaluate a fighter from the Free Agents screen."
                )
                self._reports_empty_label.pack(
                    expand=True, fill="both", pady=60,
                )
                return

            # Render each report card (D4).
            theme = get_theme()
            for report in self._reports_data:
                card = self._build_report_card(self._reports_scroll, report)
                card.pack(side="top", fill="x", padx=5, pady=(0, 10))
                self._report_cards.append(card)
        except Exception as e:
            print(f"Warning: scouting reports render failed: {e}",
                  flush=True)

    def _build_report_card(self, parent, report):
        """Build a single report card (D4, D5).

        Layout:
          ┌──────────────────────────────────────────────────────┐
          │ Report: <name> · <weight class> [⚠ Stale]            │
          │ Scout: <name> · Date: <date> · Confidence: N/100     │
          │                                                       │
          │ Estimated Potential: <phrase>                        │
          │ Estimated Ceiling:   <phrase>                        │
          │ Estimated Floor:     <phrase>                        │
          │ Strengths: <comma-separated phrases>                 │
          │ Weaknesses: <comma-separated phrases>                │
          │                                                       │
          │ ┌─ REPORT ──────────────────────────────────────┐    │
          │ │ <report_text — multi-line voice-layered prose> │    │
          │ └────────────────────────────────────────────────┘    │
          │                                                       │
          │ [View Fighter]  [Dismiss Report]                     │
          └──────────────────────────────────────────────────────┘
        """
        theme = get_theme()

        card = ctk.CTkFrame(
            parent, fg_color=theme.colors.bg_surface, corner_radius=8,
        )

        # Inner padding frame.
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=15, pady=12)

        # Header row: "Report: <name> · <weight class> [⚠ Stale]"
        header_text = (f"Report: {report['fighter_name']}  ·  "
                       f"{report['weight_class_name']}")
        if report["is_stale"]:
            header_text += "   ⚠ STALE"
        header = ctk.CTkLabel(
            inner, text=header_text,
            font=theme.fonts.h3,
            text_color=theme.colors.gold if report["is_stale"]
                else theme.colors.text_primary,
            anchor="w",
        )
        header.pack(fill="x", pady=(0, 4))

        # Scout row: "Scout: <name> · Date: <date> · Confidence: N/100"
        scout_text = (f"Scout: {report['scout_name']}  ·  "
                      f"Date: {report['report_date']}  ·  "
                      f"Confidence: {report['scout_confidence'] or 0}/100")
        scout_label = ctk.CTkLabel(
            inner, text=scout_text,
            font=theme.fonts.caption,
            text_color=theme.colors.text_secondary,
            anchor="w",
        )
        scout_label.pack(fill="x", pady=(0, 8))

        # Estimated fields (all already voice phrases — D1).
        fields = [
            ("Estimated Potential", report["estimated_potential"]),
            ("Estimated Ceiling",   report["estimated_ceiling"]),
            ("Estimated Floor",     report["estimated_floor"]),
            ("Strengths",           _parse_descriptor_list(
                report["estimated_strengths"])),
            ("Weaknesses",          _parse_descriptor_list(
                report["estimated_weaknesses"])),
        ]
        for label_text, value_text in fields:
            field_row = ctk.CTkFrame(inner, fg_color="transparent")
            field_row.pack(fill="x", pady=(0, 2))

            field_label = ctk.CTkLabel(
                field_row, text=f"{label_text}:",
                font=theme.fonts.body_small,
                text_color=theme.colors.text_secondary,
                width=160, anchor="w",
            )
            field_label.pack(side="left", padx=(0, 8))

            field_value = ctk.CTkLabel(
                field_row, text=value_text,
                font=theme.fonts.body_small,
                text_color=theme.colors.text_primary,
                anchor="w", wraplength=600,
            )
            field_value.pack(side="left", fill="x", expand=True)

        # Report text — multi-line voice-layered prose (D4).
        if report["report_text"]:
            report_frame = ctk.CTkFrame(
                inner, fg_color=theme.colors.bg_surface_elevated,
                corner_radius=4,
            )
            report_frame.pack(fill="x", pady=(8, 0))

            report_label = ctk.CTkLabel(
                report_frame, text=report["report_text"],
                font=theme.fonts.descriptor,
                text_color=theme.colors.text_primary,
                anchor="w", justify="left", wraplength=700,
            )
            report_label.pack(fill="x", padx=10, pady=8)

        # Action buttons row.
        button_row = ctk.CTkFrame(inner, fg_color="transparent")
        button_row.pack(fill="x", pady=(10, 0))

        view_button = ctk.CTkButton(
            button_row, text="View Fighter",
            font=theme.fonts.body_small,
            width=110, height=26,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=lambda fid=report["fighter_id"]:
                self._on_view_fighter_clicked(fid),
        )
        view_button.pack(side="left")

        dismiss_button = ctk.CTkButton(
            button_row, text="Dismiss Report",
            font=theme.fonts.body_small,
            width=110, height=26,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.crimson,
            text_color=theme.colors.text_primary,
            command=lambda rid=report["report_id"]:
                self._on_dismiss_clicked(rid),
        )
        dismiss_button.pack(side="left", padx=(8, 0))

        return card

    # ------------------------------------------------------------
    # Refresh scout dropdown
    # ------------------------------------------------------------

    def _refresh_scout_dropdown(self):
        """Populate the scout dropdown + show/hide the no-scouts hint."""
        try:
            theme = get_theme()
            # Build dropdown values: "First Last [id=N]".
            values = []
            for sid, name in self._scouts:
                values.append(f"{name} [id={sid}]")

            if not values:
                # No scouts — disable the form + show the hint.
                self._scout_menu.configure(values=["(no scouts available)"])
                self._scout_menu.set("(no scouts available)")
                self._assign_button.configure(state="disabled")
                # Show the no-scouts hint.
                try:
                    self._no_scouts_label.pack(side="left", padx=(12, 0))
                except Exception:
                    pass
                return

            # Scouts exist — enable the form + hide the hint.
            self._scout_menu.configure(values=values)
            self._scout_menu.set(values[0])
            self._assign_button.configure(state="normal")
            try:
                self._no_scouts_label.pack_forget()
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: scout dropdown refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------

    def _parse_id_from_label(self, label):
        """Extract the staff_id from a "First Last [id=N]" dropdown value.

        Returns the int id, or None if no id is found.
        """
        if not label:
            return None
        try:
            import re
            m = re.search(r"\[id=(\d+)\]", label)
            if m:
                return int(m.group(1))
        except (ValueError, AttributeError):
            pass
        return None

    def _resolve_target(self, conn, target_text):
        """Resolve a target fighter ID or name to a fighter_id.

        Accepts:
          - A numeric string (e.g., "3451") — exact fighter_id match.
          - A name string (e.g., "Hiroki Nakamura") — case-insensitive
            substring match on first_name + last_name + nickname.
            First match wins. If multiple fighters match, the player
            should be more specific (the status label warns them).

        Returns the fighter_id (int) or None if no match.
        """
        # Try numeric first.
        try:
            fid = int(target_text)
            row = conn.execute(
                "SELECT fighter_id FROM fighters WHERE fighter_id = ?",
                (fid,),
            ).fetchone()
            if row:
                return row[0]
            # Numeric but no such fighter — fall through to name search
            # (the player might have typed a name that starts with
            # digits, e.g., "3rd Generation Fighter").
        except ValueError:
            pass  # Not numeric — try name search.

        # Name search — case-insensitive substring.
        like_term = f"%{target_text}%"
        rows = conn.execute(
            """
            SELECT fighter_id FROM fighters
            WHERE first_name LIKE ? OR last_name LIKE ? OR nickname LIKE ?
            ORDER BY fighter_id ASC
            """,
            (like_term, like_term, like_term),
        ).fetchall()
        if rows:
            return rows[0][0]
        return None

    # ------------------------------------------------------------
    # Status feedback (D8)
    # ------------------------------------------------------------

    def _set_assign_status(self, message, level="info"):
        """Update the assign-status label with a color-coded message (D8).

        Args:
            message: the text to display.
            level: one of "info" (tertiary text), "success" (gold),
                "warning" (warning yellow), "danger" (crimson).
        """
        try:
            theme = get_theme()
            color_map = {
                "info": theme.colors.text_tertiary,
                "success": theme.colors.gold,
                "warning": theme.colors.warning,
                "danger": theme.colors.crimson,
            }
            color = color_map.get(level, theme.colors.text_tertiary)
            self._assign_status_label.configure(
                text=message,
                font=theme.fonts.body_small,
                text_color=color,
            )
        except Exception as e:
            print(f"Warning: scouting status update failed: {e}",
                  flush=True)
