"""CAGE EMPIRE — Fighter Profile screen (Stage 6 — Task 6.4).

The Fighter Profile — the OTHER highest-traffic screen in CAGE
EMPIRE (along with the Roster). Shows a single fighter's full
interpretation: career phase, momentum, pressure, narrative
family, legacy state, trajectory, bio, career stats, recent
fights, all 26 attributes as voice descriptors, all 20
personality traits as voice descriptors.

This is the screen where the "Rich Not Thin" principle (§17.4) is
most visible. Every fighter is rendered as a collection of voice
phrases — never a raw attribute number anywhere.

Per docs/GUI_PLAN.md §5.2 (FIGHTERS group):
  "The big profile screen — headshot + bio + 28 attributes
  (descriptors) + personality + career record + recent fights +
  contracts + injuries + social posts + memory links + training
  camp."

  Listed primary tables include `fighter_attributes` +
  `fighter_personality` — but per CONVENTIONS §17 (UI Snapshot
  Rule — CRITICAL), the Fighter Profile reads ONLY from cache +
  game-state tables. The actual source map is:

    - `fighters` (game state — name, nickname, weight_class_id,
      current_gym_id, current_promotion_id, date_of_birth. Names
      are NOT raw attribute values per §14.)
    - `fighter_descriptors` (cache — career_phase, momentum,
      pressure, narrative_family, legacy_state voice phrases +
      attribute_descriptors JSON + personality_descriptors JSON
      per §17.3. The interpretation layer is the only writer.)
    - `fighter_career` (game state — record_wins, record_losses,
      record_draws, win_streak, loss_streak, title_reigns. Career
      stats are OK per §14.)
    - `fighter_bios` (game state — bio_text. The supervisor's
      original bio. Per the Task 6.4 brief: "fighter_bios — bio_text
      (the supervisor's original bio)". NOT a raw attribute table.)
    - `weight_classes` (game state — name. NOT a fighter attribute.)
    - `gyms` (game state — name. NOT a fighter attribute.)
    - `promotions` (game state — name. NOT a fighter attribute.)
    - `fight_history` (game state — opponent_id, outcome,
      result_type, finish_round, event_date. Career stats, OK per
      §14. The opponent's name comes from `fighters` via JOIN —
      names are OK per §14. NEVER reads from the opponent's
      fighter_attributes / fighter_personality / fighter_career
      other than name.)
    - `titles` (game state — current_champion_fighter_id. Used to
      check if THIS fighter is a champion. NOT a fighter attribute
      table.)

  This screen NEVER reads from `fighter_attributes` (raw 0-100
  values), `fighter_personality` (raw trait values),
  `fighter_contracts` (simulation table per §17.3). See D1.

Per docs/CONVENTIONS.md §14 (Interpretation Layer — CRITICAL):
  No raw attribute values appear in the player-facing UI.
    - Career phase → decoded voice phrase — never the raw label,
      never the underlying numbers that produced it.
    - Momentum → decoded voice phrase — never the raw label.
    - Pressure → decoded voice phrase.
    - Narrative family → decoded voice phrase, or "(none)" if NULL.
    - Legacy state → decoded voice phrase.
    - Trajectory → derived (D6) + decoded voice phrase.
    - Record → "18-5-0" — OK per §14 (career stats).
    - Win/loss streaks → "Win streak: 3" — OK per §14 (career
      stats; the streak COUNT is a career stat, not an attribute).
    - Title reigns → "3 title reigns" — OK per §14 (career stats).
    - All 26 attributes → voice descriptors from the
      attribute_descriptors JSON (e.g., "carries real knockout
      power"). NEVER the raw 0-100 value.
    - All 20 personality traits → voice descriptors from the
      personality_descriptors JSON (e.g., "measured aggression").
      NEVER the raw 0-100 value.

Per docs/CONVENTIONS.md §17.4 ("Rich Not Thin" — CRITICAL):
  Every cache label has an associated voice phrase. The cache
  stores "label||phrase"; the UI shows the phrase. The Fighter
  Profile uses `interpretation.context_engine.decode_phrase`
  (single source of truth) to extract the phrase. The
  attribute_descriptors + personality_descriptors JSON columns
  store the descriptors DIRECTLY (no "||" prefix) — they were
  computed by voice.build_descriptor_snapshot which already
  applied voice.py's describe_attribute / describe_personality.
  The UI just parses the JSON + displays.

Architecture (mirrors DashboardScreen — same pattern all Office
Mode screens follow):
  - FighterProfileScreen(ctk.CTkFrame) — the screen widget.
  - set_fighter_id(fighter_id) — called by the Roster BEFORE
    navigating. Stores the fighter_id + triggers a refresh.
  - _build_back_button() — "← Back to Roster" navigation.
  - _build_header() — H1 name + nickname + "WC · Promo · Gym"
    subtitle.
  - _build_identity_block() — 6 voice phrases (career phase,
    momentum, pressure, narrative, legacy, trajectory).
  - _build_bio_section() — bio_text from fighter_bios.
  - _build_career_section() — record, streaks, title reigns,
    champion status.
  - _build_recent_fights() — last 5 fight_history rows.
  - _build_attribute_profile() — 26 attributes as voice
    descriptors, 2-column grid.
  - _build_personality() — 20 traits as voice descriptors,
    2-column grid.
  - _refresh() — registered with GameState; re-queries the
    fighter's full data + re-renders every section.

Navigation:
  - Back button → state.set_active_screen("roster").
  - The Roster calls set_fighter_id(fighter_id) BEFORE calling
    state.set_active_screen("fighter_profile"). The Fighter
    Profile screen then renders that fighter on its _refresh()
    (which fires via set_active_screen → state.refresh).

DESIGN DECISIONS (D-numbers — referenced from the worklog):
  D1  Source-of-truth map. See the §17 comment block above. The
      rule: fighter INTERPRETATION data (career_phase, momentum,
      pressure, narrative_family, legacy_state, attribute
      descriptors, personality descriptors) comes from
      fighter_descriptors cache ONLY. Fighter NAMES +
      weight_class_id + current_gym_id + current_promotion_id +
      date_of_birth come from `fighters` (game state). Career
      stats (record, streaks, title_reigns) from `fighter_career`
      (career stats — OK per §14). Bio from `fighter_bios` (the
      supervisor's original prose). Weight class / gym / promotion
      NAMES from `weight_classes` / `gyms` / `promotions` (game
      state). Recent fights from `fight_history` (career stats).
      Champion status from `titles` (game state). The Fighter
      Profile NEVER touches fighter_attributes /
      fighter_personality / fighter_contracts / injuries /
      training_camps / social_posts / scouting_reports /
      fighter_memory_links.

      Note on fighter_career + fight_history: §17.3 lists both as
      simulation tables (the interpretation layer never writes to
      them). However, §14 explicitly permits "career stats"
      (record, streaks, title reigns, fight results) in the UI —
      they are NOT raw attribute values. The Fighter Profile
      reads ONLY career-stat columns from these tables — never
      `potential`, never `career_health` (those are §14-protected
      raw values).

  D2  set_fighter_id + late refresh. The Roster calls
      set_fighter_id(fighter_id) BEFORE navigating. The method
      stores the fighter_id on self._fighter_id + calls _refresh()
      immediately (so the screen is fully rendered by the time
      _navigate packs it). set_active_screen("fighter_profile")
      then triggers state.refresh("fighter_profile"), which calls
      _refresh() AGAIN — harmless (idempotent). The double-refresh
      is intentional: set_fighter_id's immediate refresh ensures
      the screen is ready even if state.refresh somehow doesn't
      fire (e.g., if the screen was already active, which
      shouldn't happen but defensive).

  D3  Trajectory derivation. Per context_engine.D6, trajectory
      isn't stored as a cache column — it's derived on-demand
      from momentum + age. The Fighter Profile calls
      `compute_trajectory_for_fighter(conn, fighter_id)` which
      reads fighter_descriptors.momentum (cache) + fighters.
      date_of_birth (game state), applies compute_trajectory, and
      returns the canonical label. The label is then passed to
      `get_trajectory_phrase` to get the voice phrase. Both
      helpers live in interpretation.context_engine — single
      source of truth. This is §17-compliant: the only DB reads
      are from the cache (fighter_descriptors) + game-state
      (fighters.date_of_birth — a date, not an attribute).

  D4  Scrollable root. The Fighter Profile's content always
      exceeds the viewport (26 attributes + 20 personality traits
      + bio + recent fights + identity block = ~60 rows of
      content). The root container is a CTkScrollableFrame so the
      whole screen scrolls naturally. Cards inside keep their own
      bg_surface background so they read as discrete panels (same
      pattern as DashboardScreen.D5).

  D5  Defensive against missing data. Every section degrades
      gracefully:
      - No fighter_id set → "No fighter selected. Return to the
        Roster and pick a fighter."
      - fighter_id not in DB → "Fighter not found." (Shouldn't
        happen — the Roster only shows existing fighter_ids — but
        defensive.)
      - No fighter_descriptors row → identity block shows
        "(uncached)" for each phrase; attribute/personality
        sections show "Attribute descriptors not yet computed."
      - No fighter_bios row → bio section shows "No bio available
        for this fighter."
      - No fighter_career row → career section shows "0-0-0"
        record + "No career stats available."
      - No fight_history rows → recent fights section shows "No
        fights on record yet."
      - No titles (not a champion) → career section omits the
        "Current Champion" badge.

  D6  Identity block layout. The 6 voice phrases are rendered as
      a 2-column grid (label | phrase) inside a card. Labels are
      gold (matches Dashboard's H2 panel titles); phrases are
      text_primary (high contrast). The grid is 2 columns wide so
      the block reads as a compact summary, not a tall list.

  D7  Attribute + personality grid layout. The 26 attributes are
      rendered as a 2-column grid (label | descriptor) — same
      pattern as the identity block. 26 attributes / 2 columns =
      13 rows. The 20 personality traits are similarly a 2-column
      grid = 10 rows. Both grids are inside their own card with
      a gold H2 section title ("ATTRIBUTE PROFILE" /
      "PERSONALITY"). The attribute order is grouped logically
      (striking → clinch/wrestling → grappling → durability →
      physical → mental) so the player can scan by category. The
      personality order is similarly grouped (combat behavior →
      mental toughness → social → career). See
      _ATTRIBUTE_DISPLAY_ORDER + _PERSONALITY_DISPLAY_ORDER.

  D8  Recent fights layout. Each fight is a row:
        [W/L] vs Opponent Name (result_type, R{round}) · date
      The W/L badge is colored (gold for win, crimson for loss,
      steel for draw) so the player can scan the recent form at a
      glance. The result_type is human-readable-ized (e.g.,
      "ko_tko" → "KO/TKO", "unanimous_decision" → "Decision").
      Fights are ordered most-recent-first (ORDER BY event_date
      DESC) so the latest fight is at the top.

  D9  Champion badge. If the fighter is currently a champion
      (titles.current_champion_fighter_id = fighter_id), a gold
      "CHAMPION" badge is rendered in the career section. This is
      game-state data (titles table), NOT a fighter attribute —
      OK per §14. The badge is a visual flourish that makes the
      profile feel alive when the player is looking at a champion.

  D10 Refresh pattern. Following DashboardScreen: dynamic widgets
       are tracked in instance lists (_identity_widgets,
       _bio_widgets, _career_widgets, _fights_widgets,
       _attr_widgets, _pers_widgets). _refresh() destroys them,
       re-queries, re-renders. Static structure (H1 title, section
       titles, scrollable frames) is built once in __init__.
       Theme-change refresh (state.refresh_all after set_theme)
       re-renders with the new theme's colors/fonts because every
       widget construction calls get_theme() at render time.
"""

import json
import sqlite3

import customtkinter as ctk

from ui.theme import get_theme
from ui.state import get_state

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (mirrors
# DashboardScreen's D4).
from interpretation.context_engine import (
    decode_phrase,
    compute_trajectory_for_fighter,
    get_trajectory_phrase,
)
import random


# ============================================================
# CONSTANTS — display ordering
# ============================================================

# Attribute display order. Groups attributes into logical categories
# so the player can scan by category (striking → clinch/wrestling →
# grappling → durability → physical → mental). Any attribute in the
# JSON not in this list is appended at the end (defensive against
# schema drift — D5).
_ATTRIBUTE_DISPLAY_ORDER = [
    # Striking
    "punch_power", "punch_accuracy",
    "kick_power", "kick_accuracy",
    "head_movement", "footwork",
    "clinch_striking",
    # Clinch & Wrestling
    "clinch_offense", "clinch_defense",
    "cage_wrestling",
    "takedown_offense", "takedown_defense",
    "top_control", "bottom_game",
    "scramble_ability",
    # Grappling
    "submission_offense", "submission_defense",
    # Durability
    "chin", "durability", "recovery_rate", "cardio",
    # Physical
    "strength", "speed_explosiveness", "flexibility",
    # Mental
    "fight_iq", "adaptability",
]

# Personality display order. Groups traits into logical categories
# (combat behavior → mental toughness → social → career).
_PERSONALITY_DISPLAY_ORDER = [
    # Combat behavior
    "aggression", "composure", "risk_taking",
    "killer_instinct", "patience",
    # Mental toughness
    "focus", "discipline", "grit",
    "resilience", "fatigue_tolerance",
    # Social
    "charisma", "ego", "attention_seeking", "sportsmanship",
    # Career
    "ambition", "loyalty", "coachability",
    "professionalism", "morale", "travel_comfort",
]

# Human-readable result_type labels. The fight_history.result_type
# column stores snake_case (e.g., "ko_tko", "unanimous_decision"). The
# UI shows the human-readable form (e.g., "KO/TKO", "Decision"). Per
# §14, this is a career-stat label, not an attribute value — OK to
# display.
_RESULT_TYPE_LABELS = {
    "ko_tko": "KO/TKO",
    "submission": "Submission",
    "unanimous_decision": "Decision",
    "split_decision": "Split Decision",
    "draw": "Draw",
    "doctor_stoppage": "Doctor Stoppage",
    "dq": "DQ",
}


# ============================================================
# HELPERS
# ============================================================

def _format_name(first, last, nickname):
    """Format a fighter's name with optional nickname in quotes.

    Mirrors RosterScreen._format_name exactly — single source of
    truth for fighter name formatting across Office Mode screens.
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


def _format_record(wins, losses, draws):
    """Format a fighter's record as 'W-L-D'.

    Per §14: career stats (record) are explicitly OK to display as
    numbers. Mirrors RosterScreen._format_record.
    """
    try:
        w = int(wins or 0)
    except (TypeError, ValueError):
        w = 0
    try:
        l = int(losses or 0)
    except (TypeError, ValueError):
        l = 0
    try:
        d = int(draws or 0)
    except (TypeError, ValueError):
        d = 0
    return f"{w}-{l}-{d}"


def _phrase_or_fallback(stored_value, fallback):
    """Decode a "label||phrase" cache value, or return a fallback.

    Mirrors RosterScreen._phrase_or_fallback — single source of
    truth for cache-column decode across Office Mode screens.
    """
    phrase = decode_phrase(stored_value)
    return phrase if phrase else fallback


def _humanize_attr_name(attr_name):
    """Convert a snake_case attribute name to a human-readable label.

    Examples:
        punch_power → Punch Power
        fight_iq → Fight IQ
        takedown_defense → Takedown Defense
    """
    if not attr_name:
        return ""
    # Special-case: fight_iq → "Fight IQ" (not "Fight Iq")
    if attr_name == "fight_iq":
        return "Fight IQ"
    return attr_name.replace("_", " ").title()


def _humanize_trait_name(trait_name):
    """Convert a snake_case trait name to a human-readable label.

    Examples:
        risk_taking → Risk Taking
        killer_instinct → Killer Instinct
    """
    if not trait_name:
        return ""
    return trait_name.replace("_", " ").title()


def _result_type_label(result_type):
    """Convert a fight_history.result_type to a human-readable label.

    Returns the raw value title-cased if the result_type isn't in
    the lookup table (defensive — new result types may be added by
    future schema bumps).
    """
    if not result_type:
        return ""
    return _RESULT_TYPE_LABELS.get(
        result_type, result_type.replace("_", " ").title())


def _outcome_badge(outcome):
    """Return (label, color) for a fight outcome.

    Used by the Recent Fights section to color the W/L/D badge:
      win  → "W" (gold)
      loss → "L" (crimson)
      draw → "D" (steel)

    Per §14: career stats (outcome) are OK to display. The badge is
    a single character — the color carries the semantic weight.
    """
    if outcome == "win":
        return "W", get_theme().colors.gold
    if outcome == "loss":
        return "L", get_theme().colors.crimson
    if outcome == "draw":
        return "D", get_theme().colors.steel
    return "?", get_theme().colors.text_tertiary


# ============================================================
# FIGHTER PROFILE SCREEN
# ============================================================

class FighterProfileScreen(ctk.CTkFrame):
    """Fighter Profile — a single fighter's full interpretation.

    The HIGHEST-TRAFFIC screen in CAGE EMPIRE alongside the Roster
    (per GUI_PLAN §5.7). Office Mode only (NOT a Fight Night
    screen). Registered with GameState as 'fighter_profile'. The
    refresh callback (`_refresh`) re-queries the currently-set
    fighter's full data + re-renders every section.

    Usage:
        screen = FighterProfileScreen(parent_frame)
        state.register_screen("fighter_profile", screen, screen._refresh)
        # From the Roster, before navigating:
        screen.set_fighter_id(fighter_id)
        state.set_active_screen("fighter_profile")
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # Configure the screen's own background to match the Office
        # Mode base — cards inside sit on top of this.
        theme = get_theme()
        self.configure(fg_color=theme.colors.bg_base)

        # The fighter_id to display. Set by set_fighter_id() before
        # navigation. None = "no fighter selected" (D5).
        self._fighter_id = None

        # Dynamic-widget tracking. _refresh destroys these before
        # re-rendering. See D10.
        self._header_widgets = []
        self._identity_widgets = []
        self._bio_widgets = []
        self._career_widgets = []
        self._fights_widgets = []
        self._attr_widgets = []
        self._pers_widgets = []

        # Scrollable root container (D4). Holds all the cards.
        self._scroll = None
        # Header label (name + subtitle) — kept as attributes so
        # _refresh can call .configure() on them without recreating.
        self._name_label = None
        self._subtitle_label = None
        # Content containers — built once, populated by _refresh.
        self._identity_content = None
        self._bio_content = None
        self._career_content = None
        self._fights_content = None
        self._attr_content = None
        self._pers_content = None
        self._empty_label = None

        # Build the static structure. Dynamic content is rendered by
        # _refresh.
        self._build_back_button()
        self._build_scroll_root()
        self._build_header()
        self._build_identity_block()
        self._build_bio_section()
        self._build_career_section()
        self._build_recent_fights()
        self._build_attribute_profile()
        self._build_personality()

        # Initial render — shows the "no fighter selected" empty
        # state until set_fighter_id is called.
        # Use after(50, ...) so the widget is fully laid out before
        # we query (matches DashboardScreen pattern).
        self.after(50, self._refresh)

    # ============================================================
    # PUBLIC API — set_fighter_id (called by Roster before nav)
    # ============================================================

    def set_fighter_id(self, fighter_id):
        """Set the fighter to display + trigger an immediate refresh.

        Per D2: the Roster calls this BEFORE calling
        state.set_active_screen("fighter_profile"). The immediate
        _refresh() ensures the screen is fully rendered by the time
        _navigate packs it. set_active_screen then triggers
        state.refresh("fighter_profile") which calls _refresh() again
        — harmless (idempotent).

        Args:
            fighter_id: int — the fighter_id to display.
        """
        try:
            self._fighter_id = int(fighter_id)
        except (TypeError, ValueError):
            self._fighter_id = None
        # Immediate refresh so the screen is ready before navigation.
        self._refresh()

    # ============================================================
    # SECTION 0 — BACK BUTTON
    # ============================================================

    def _build_back_button(self):
        """Build the '← Back to Roster' button at the top.

        Per the brief's mockup: a single back button at the top-left
        of the screen. Navigates via state.set_active_screen("roster").
        """
        theme = get_theme()
        back_row = ctk.CTkFrame(self, fg_color="transparent")
        back_row.pack(side="top", fill="x", padx=20, pady=(10, 0))

        back_btn = ctk.CTkButton(
            back_row, text="← Back to Roster",
            font=theme.fonts.body,
            width=160, height=28,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_back,
        )
        back_btn.pack(side="left")

    def _on_back(self):
        """Navigate back to the Roster screen."""
        try:
            get_state().set_active_screen("roster")
        except (ValueError, Exception) as e:
            print(f"Warning: navigation back to roster failed: {e}",
                  flush=True)

    # ============================================================
    # SECTION 1 — SCROLLABLE ROOT (D4)
    # ============================================================

    def _build_scroll_root(self):
        """Build the scrollable root container.

        Per D4: the Fighter Profile's content always exceeds the
        viewport. The root is a CTkScrollableFrame so the whole
        screen scrolls naturally. Cards inside keep their own
        bg_surface background so they read as discrete panels.
        """
        theme = get_theme()
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=theme.colors.bg_base,
            corner_radius=0,
        )
        self._scroll.pack(side="top", fill="both", expand=True, padx=0, pady=(10, 0))

    # ============================================================
    # SECTION 2 — HEADER (H1 name + WC · Promo · Gym subtitle)
    # ============================================================

    def _build_header(self):
        """Build the H1 name + subtitle ('WC · Promo · Gym')."""
        theme = get_theme()

        # Name label (H1) — populated by _refresh.
        self._name_label = ctk.CTkLabel(
            self._scroll, text="No fighter selected",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w",
        )
        self._name_label.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # Subtitle — populated by _refresh.
        self._subtitle_label = ctk.CTkLabel(
            self._scroll, text="",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        self._subtitle_label.pack(side="top", fill="x", padx=20, pady=(0, 10))

    # ============================================================
    # SECTION 3 — IDENTITY BLOCK (6 voice phrases)
    # ============================================================

    def _build_identity_block(self):
        """Build the identity block: 6 voice phrases in a 2-col grid.

        Per D6: rendered as a 2-column grid (label | phrase) inside a
        card. Labels are gold; phrases are text_primary. The 6 phrases:
          - CAREER PHASE
          - MOMENTUM
          - PRESSURE
          - NARRATIVE
          - LEGACY
          - TRAJECTORY
        """
        theme = get_theme()

        # Card container
        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="IDENTITY",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        # Content container — populated by _refresh as a 2-col grid.
        self._identity_content = ctk.CTkFrame(card, fg_color="transparent")
        self._identity_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 4 — BIO
    # ============================================================

    def _build_bio_section(self):
        """Build the bio section: bio_text from fighter_bios."""
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="── BIO ──",
            font=theme.fonts.h3, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._bio_content = ctk.CTkFrame(card, fg_color="transparent")
        self._bio_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 5 — CAREER (record, streaks, title reigns, champion)
    # ============================================================

    def _build_career_section(self):
        """Build the career section: record + streaks + reigns + champ."""
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="── CAREER ──",
            font=theme.fonts.h3, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._career_content = ctk.CTkFrame(card, fg_color="transparent")
        self._career_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 6 — RECENT FIGHTS (last 5)
    # ============================================================

    def _build_recent_fights(self):
        """Build the recent fights section: last 5 fight_history rows."""
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="── RECENT FIGHTS ──",
            font=theme.fonts.h3, text_color=theme.colors.text_secondary,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._fights_content = ctk.CTkFrame(card, fg_color="transparent")
        self._fights_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 7 — ATTRIBUTE PROFILE (26 attributes, 2-col grid)
    # ============================================================

    def _build_attribute_profile(self):
        """Build the attribute profile: 26 attributes, 2-col grid.

        Per D7: rendered as a 2-column grid (label | descriptor).
        26 attributes / 2 columns = 13 rows. Inside its own card with
        a gold H2 section title ("ATTRIBUTE PROFILE").
        """
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="ATTRIBUTE PROFILE",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._attr_content = ctk.CTkFrame(card, fg_color="transparent")
        self._attr_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 8 — PERSONALITY (20 traits, 2-col grid)
    # ============================================================

    def _build_personality(self):
        """Build the personality section: 20 traits, 2-col grid.

        Per D7: rendered as a 2-column grid (label | descriptor).
        20 traits / 2 columns = 10 rows. Inside its own card.
        """
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="PERSONALITY",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._pers_content = ctk.CTkFrame(card, fg_color="transparent")
        self._pers_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # REFRESH CALLBACK (registered with GameState)
    # ============================================================

    def _refresh(self):
        """Refresh callback — re-query the fighter + re-render.

        Registered with GameState as this screen's refresh callback.
        Called:
          - Once on init (via after(50, ...)).
          - On every navigation to this screen (set_active_screen
            triggers state.refresh(name)).
          - On refresh_all() (after Advance Day, Save, Load, theme
            toggle).
          - Immediately by set_fighter_id() so the screen is ready
            before navigation (D2).

        Safe to call repeatedly — destroys old dynamic widgets,
        re-queries, re-renders. Defensive against DB errors.
        """
        try:
            state = get_state()
            conn = state.get_conn()
            if conn is None:
                return

            # Destroy all dynamic widgets from the previous render.
            self._destroy_dynamic_widgets()

            # If no fighter is set, show the empty state.
            if self._fighter_id is None:
                self._render_empty_state("No fighter selected. Return to the Roster and pick a fighter.")
                return

            # Query the fighter's full data.
            data = self._query_fighter(conn, self._fighter_id)
            if data is None:
                self._render_empty_state("Fighter not found.")
                return

            # Render every section.
            self._refresh_header(data)
            self._refresh_identity(conn, data)
            self._refresh_bio(data)
            self._refresh_career(conn, data)
            self._refresh_recent_fights(conn, data)
            self._refresh_attribute_profile(data)
            self._refresh_personality(data)
        except Exception as e:
            print(f"Warning: FighterProfileScreen._refresh failed: {e}",
                  flush=True)

    def _destroy_dynamic_widgets(self):
        """Destroy all dynamic widgets from the previous render.

        Per D10: tracked in instance lists. Safe to call when the
        lists are empty (initial render).
        """
        for widget_list in (
            self._header_widgets, self._identity_widgets,
            self._bio_widgets, self._career_widgets,
            self._fights_widgets, self._attr_widgets,
            self._pers_widgets,
        ):
            for w in widget_list:
                try:
                    w.destroy()
                except Exception:
                    pass
            widget_list.clear()

    def _render_empty_state(self, message):
        """Show a single 'empty state' message in the header area.

        Per D5: used when no fighter is selected or the fighter_id
        isn't found. Clears the name + subtitle labels + shows the
        message in the name label position.
        """
        try:
            theme = get_theme()
            self._name_label.configure(
                text=message,
                font=theme.fonts.h2,
                text_color=theme.colors.text_tertiary,
            )
            self._subtitle_label.configure(text="")
        except Exception as e:
            print(f"Warning: empty-state render failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Query the fighter's full data
    # ------------------------------------------------------------

    def _query_fighter(self, conn, fighter_id):
        """Query the fighter's full data in a single JOIN.

        Per D1: reads from fighters (game state — names + IDs) +
        weight_classes + gyms + promotions (game state — names) +
        fighter_descriptors (cache — voice phrases + JSON) +
        fighter_career (career stats only — §14 OK).

        Returns:
            dict with all the data the section renderers need, or
            None if the fighter_id isn't found.
        """
        try:
            row = conn.execute(
                """
                SELECT f.fighter_id, f.first_name, f.last_name, f.nickname,
                       f.weight_class_id, wc.name AS wc_name, wc.gender,
                       f.current_gym_id, g.name AS gym_name,
                       f.current_promotion_id, p.name AS promo_name,
                       f.date_of_birth,
                       fd.career_phase, fd.momentum, fd.pressure,
                       fd.narrative_family, fd.legacy_state,
                       fd.attribute_descriptors, fd.personality_descriptors,
                       fd.overall_desc,
                       fc.record_wins, fc.record_losses, fc.record_draws,
                       fc.win_streak, fc.loss_streak, fc.title_reigns,
                       fb.bio_text
                FROM fighters f
                LEFT JOIN weight_classes wc
                  ON wc.weight_class_id = f.weight_class_id
                LEFT JOIN gyms g
                  ON g.gym_id = f.current_gym_id
                LEFT JOIN promotions p
                  ON p.promotion_id = f.current_promotion_id
                LEFT JOIN fighter_descriptors fd
                  ON fd.fighter_id = f.fighter_id
                LEFT JOIN fighter_career fc
                  ON fc.fighter_id = f.fighter_id
                LEFT JOIN fighter_bios fb
                  ON fb.fighter_id = f.fighter_id
                WHERE f.fighter_id = ?
                """,
                (fighter_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "fighter_id": row[0],
                "first_name": row[1],
                "last_name": row[2],
                "nickname": row[3],
                "weight_class_id": row[4],
                "wc_name": row[5],
                "wc_gender": row[6],
                "current_gym_id": row[7],
                "gym_name": row[8],
                "current_promotion_id": row[9],
                "promo_name": row[10],
                "date_of_birth": row[11],
                "career_phase_stored": row[12],
                "momentum_stored": row[13],
                "pressure_stored": row[14],
                "narrative_stored": row[15],
                "legacy_stored": row[16],
                "attribute_descriptors_json": row[17],
                "personality_descriptors_json": row[18],
                "overall_desc": row[19],
                "record_wins": row[20],
                "record_losses": row[21],
                "record_draws": row[22],
                "win_streak": row[23],
                "loss_streak": row[24],
                "title_reigns": row[25],
                "bio_text": row[26],
            }
        except sqlite3.Error as e:
            print(f"Warning: fighter query failed for id={fighter_id}: {e}",
                  flush=True)
            return None

    # ------------------------------------------------------------
    # Header — name + WC · Promo · Gym subtitle
    # ------------------------------------------------------------

    def _refresh_header(self, data):
        """Render the H1 name + 'WC · Promo · Gym' subtitle."""
        try:
            theme = get_theme()
            name = _format_name(
                data["first_name"], data["last_name"], data["nickname"])
            self._name_label.configure(
                text=name,
                font=theme.fonts.h1,
                text_color=theme.colors.text_primary,
            )

            # Subtitle: WC · Promo · Gym. Defensive — any missing
            # component is skipped.
            parts = []
            if data.get("wc_name"):
                wc_label = data["wc_name"]
                if data.get("wc_gender"):
                    wc_label += f" ({data['wc_gender']})"
                parts.append(wc_label)
            if data.get("promo_name"):
                parts.append(data["promo_name"])
            if data.get("gym_name"):
                parts.append(data["gym_name"])
            subtitle = "  ·  ".join(parts) if parts else ""
            self._subtitle_label.configure(
                text=subtitle,
                font=theme.fonts.body,
                text_color=theme.colors.text_secondary,
            )
        except Exception as e:
            print(f"Warning: header refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Identity block — 6 voice phrases
    # ------------------------------------------------------------

    def _refresh_identity(self, conn, data):
        """Render the 6-phrase identity block.

        Per D6: 2-column grid (label | phrase) inside the identity
        card. Labels are gold; phrases are text_primary.

        Phrases:
          - CAREER PHASE  (decoded from fighter_descriptors.career_phase)
          - MOMENTUM      (decoded from fighter_descriptors.momentum)
          - PRESSURE      (decoded from fighter_descriptors.pressure)
          - NARRATIVE     (decoded from fighter_descriptors.narrative_family
                            — "(none)" if NULL per D5)
          - LEGACY        (decoded from fighter_descriptors.legacy_state)
          - TRAJECTORY    (derived — D3)
        """
        try:
            theme = get_theme()

            # Compute the trajectory voice phrase (D3).
            trajectory_phrase = "(uncached)"
            try:
                trajectory_label = compute_trajectory_for_fighter(
                    conn, data["fighter_id"])
                if trajectory_label:
                    # Use a seeded RNG for deterministic phrase selection
                    # (so the same fighter always shows the same phrase).
                    rng = random.Random(data["fighter_id"])
                    trajectory_phrase = get_trajectory_phrase(
                        trajectory_label, rng)
            except Exception as e:
                print(f"Warning: trajectory computation failed: {e}",
                      flush=True)

            # Build the 6 phrase rows. Each is (LABEL, phrase).
            rows = [
                ("CAREER PHASE",
                 _phrase_or_fallback(data["career_phase_stored"], "(uncached)")),
                ("MOMENTUM",
                 _phrase_or_fallback(data["momentum_stored"], "(uncached)")),
                ("PRESSURE",
                 _phrase_or_fallback(data["pressure_stored"], "(uncached)")),
                ("NARRATIVE",
                 _phrase_or_fallback(data["narrative_stored"], "(none)")),
                ("LEGACY",
                 _phrase_or_fallback(data["legacy_stored"], "(uncached)")),
                ("TRAJECTORY", trajectory_phrase),
            ]

            # Render as a 2-column grid (label | phrase). Each row is
            # a CTkFrame containing two CTkLabels.
            for label_text, phrase_text in rows:
                row_frame = ctk.CTkFrame(
                    self._identity_content, fg_color="transparent")
                row_frame.pack(side="top", fill="x", pady=2)

                lbl = ctk.CTkLabel(
                    row_frame, text=f"{label_text}:",
                    font=theme.fonts.body,
                    text_color=theme.colors.gold,
                    anchor="w", width=120,
                )
                lbl.pack(side="left", padx=(0, 12))

                val = ctk.CTkLabel(
                    row_frame, text=phrase_text,
                    font=theme.fonts.body,
                    text_color=theme.colors.text_primary,
                    anchor="w", wraplength=600, justify="left",
                )
                val.pack(side="left", fill="x", expand=True)

                self._identity_widgets.append(row_frame)
        except Exception as e:
            print(f"Warning: identity refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Bio section
    # ------------------------------------------------------------

    def _refresh_bio(self, data):
        """Render the bio section: bio_text from fighter_bios.

        Per D5: empty-state "No bio available for this fighter." if
        the bio is missing.
        """
        try:
            theme = get_theme()
            bio_text = data.get("bio_text")
            if not bio_text:
                label = ctk.CTkLabel(
                    self._bio_content,
                    text="No bio available for this fighter.",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    anchor="w", wraplength=900, justify="left",
                )
                label.pack(side="top", fill="x")
                self._bio_widgets.append(label)
                return

            # The bio is long-form prose. Wrap it to ~900px wide so
            # it reads naturally. Use the body font + text_primary.
            label = ctk.CTkLabel(
                self._bio_content,
                text=bio_text,
                font=theme.fonts.body,
                text_color=theme.colors.text_primary,
                anchor="w", wraplength=900, justify="left",
            )
            label.pack(side="top", fill="x")
            self._bio_widgets.append(label)
        except Exception as e:
            print(f"Warning: bio refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Career section (record, streaks, reigns, champion)
    # ------------------------------------------------------------

    def _refresh_career(self, conn, data):
        """Render the career section: record + streaks + reigns + champ.

        Per D1: reads from fighter_career (career stats only — §14 OK)
        + titles (game state — champion status).

        Per D9: a gold "CHAMPION" badge is rendered if the fighter
        currently holds a title.
        """
        try:
            theme = get_theme()

            # Build the career stat rows.
            record_str = _format_record(
                data["record_wins"], data["record_losses"],
                data["record_draws"])
            win_streak = data.get("win_streak") or 0
            loss_streak = data.get("loss_streak") or 0
            title_reigns = data.get("title_reigns") or 0

            # Champion check — query titles for this fighter.
            is_champion = False
            champion_titles = []
            try:
                rows = conn.execute(
                    """
                    SELECT t.title_id, wc.name, p.name
                    FROM titles t
                    JOIN weight_classes wc
                      ON wc.weight_class_id = t.weight_class_id
                    JOIN promotions p
                      ON p.promotion_id = t.promotion_id
                    WHERE t.current_champion_fighter_id = ?
                      AND t.is_vacant = 0
                    """,
                    (data["fighter_id"],),
                ).fetchall()
                if rows:
                    is_champion = True
                    champion_titles = rows
            except sqlite3.Error as e:
                print(f"Warning: titles query failed: {e}", flush=True)

            # Row 1: CHAMPION badge (only if champion).
            if is_champion:
                badge_row = ctk.CTkFrame(
                    self._career_content, fg_color="transparent")
                badge_row.pack(side="top", fill="x", pady=(0, 8))

                for title_id, wc_name, promo_name in champion_titles:
                    badge = ctk.CTkLabel(
                        badge_row,
                        text=f"★ CHAMPION — {wc_name} ({promo_name})",
                        font=theme.fonts.h3,
                        text_color=theme.colors.gold,
                        anchor="w",
                    )
                    badge.pack(side="top", fill="x")
                    self._career_widgets.append(badge)

            # Row 2: Record + Win streak + Loss streak + Title reigns.
            stats_row = ctk.CTkFrame(
                self._career_content, fg_color="transparent")
            stats_row.pack(side="top", fill="x", pady=2)

            stats = [
                ("Record", record_str),
                ("Win Streak", str(win_streak)),
                ("Loss Streak", str(loss_streak)),
                ("Title Reigns", str(title_reigns)),
            ]
            for label_text, value_text in stats:
                stat_frame = ctk.CTkFrame(
                    stats_row, fg_color="transparent")
                stat_frame.pack(side="left", fill="x", expand=True, padx=4)

                lbl = ctk.CTkLabel(
                    stat_frame, text=label_text,
                    font=theme.fonts.caption,
                    text_color=theme.colors.text_secondary,
                    anchor="w",
                )
                lbl.pack(side="top", fill="x")
                self._career_widgets.append(lbl)

                val = ctk.CTkLabel(
                    stat_frame, text=value_text,
                    font=theme.fonts.mono,
                    text_color=theme.colors.text_primary,
                    anchor="w",
                )
                val.pack(side="top", fill="x")
                self._career_widgets.append(val)

            self._career_widgets.append(stats_row)
        except Exception as e:
            print(f"Warning: career refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Recent fights (last 5)
    # ------------------------------------------------------------

    def _refresh_recent_fights(self, conn, data):
        """Render the recent fights section: last 5 fight_history rows.

        Per D8: each fight is a row:
          [W/L] vs Opponent Name (result_type, R{round}) · date
        The W/L badge is colored. Fights ordered most-recent-first.
        """
        try:
            theme = get_theme()

            rows = []
            try:
                rows = conn.execute(
                    """
                    SELECT fh.event_date, fh.outcome, fh.result_type,
                           fh.finish_round, fh.title_at_stake,
                           opp.first_name, opp.last_name, opp.nickname
                    FROM fight_history fh
                    JOIN fighters opp
                      ON opp.fighter_id = fh.opponent_id
                    WHERE fh.fighter_id = ?
                    ORDER BY fh.event_date DESC
                    LIMIT 5
                    """,
                    (data["fighter_id"],),
                ).fetchall()
            except sqlite3.Error as e:
                print(f"Warning: fight_history query failed: {e}",
                      flush=True)

            if not rows:
                label = ctk.CTkLabel(
                    self._fights_content,
                    text="No fights on record yet.",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    anchor="w",
                )
                label.pack(side="top", fill="x")
                self._fights_widgets.append(label)
                return

            for (event_date, outcome, result_type, finish_round,
                 title_at_stake, opp_first, opp_last, opp_nick) in rows:
                row_frame = ctk.CTkFrame(
                    self._fights_content, fg_color="transparent")
                row_frame.pack(side="top", fill="x", pady=2)

                # Outcome badge (W/L/D)
                badge_text, badge_color = _outcome_badge(outcome)
                badge = ctk.CTkLabel(
                    row_frame, text=f" {badge_text} ",
                    font=theme.fonts.h3,
                    text_color=badge_color,
                    anchor="center", width=30,
                )
                badge.pack(side="left", padx=(0, 8))
                self._fights_widgets.append(badge)

                # Opponent name
                opp_name = _format_name(opp_first, opp_last, opp_nick)
                opp_label = ctk.CTkLabel(
                    row_frame, text=f"vs {opp_name}",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_primary,
                    anchor="w",
                )
                opp_label.pack(side="left", padx=(0, 8))
                self._fights_widgets.append(opp_label)

                # Result type + round
                result_label_str = _result_type_label(result_type)
                if finish_round and result_type not in (
                        "unanimous_decision", "split_decision", "draw"):
                    result_label_str += f", R{finish_round}"
                elif finish_round and result_type in (
                        "unanimous_decision", "split_decision"):
                    # Decisions go the distance — show "R3" if round=3
                    # as "Decision (R3)"
                    result_label_str = f"Decision (R{finish_round})"
                result_label = ctk.CTkLabel(
                    row_frame, text=f"({result_label_str})",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_secondary,
                    anchor="w",
                )
                result_label.pack(side="left", padx=(0, 8))
                self._fights_widgets.append(result_label)

                # Title at stake marker
                if title_at_stake:
                    title_marker = ctk.CTkLabel(
                        row_frame, text="★ TITLE",
                        font=theme.fonts.caption,
                        text_color=theme.colors.gold,
                        anchor="w",
                    )
                    title_marker.pack(side="left", padx=(0, 8))
                    self._fights_widgets.append(title_marker)

                # Date (right-aligned)
                date_str = str(event_date)[:10] if event_date else ""
                date_label = ctk.CTkLabel(
                    row_frame, text=f"· {date_str}",
                    font=theme.fonts.caption,
                    text_color=theme.colors.text_tertiary,
                    anchor="e",
                )
                date_label.pack(side="right")
                self._fights_widgets.append(date_label)

                self._fights_widgets.append(row_frame)
        except Exception as e:
            print(f"Warning: recent fights refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Attribute profile (26 attributes, 2-col grid)
    # ------------------------------------------------------------

    def _refresh_attribute_profile(self, data):
        """Render the attribute profile: 26 attributes, 2-col grid.

        Per D7: 2-column grid (label | descriptor). Each cell shows
        the attribute name (gold, smaller) + the voice descriptor
        (text_primary). The attribute_descriptors JSON stores the
        descriptors DIRECTLY (no "||" prefix) — voice.py already
        applied describe_attribute when building the snapshot.
        """
        try:
            theme = get_theme()

            # Parse the JSON. Defensive — if missing/malformed, show
            # the empty-state (D5).
            attrs = {}
            json_str = data.get("attribute_descriptors_json")
            if json_str:
                try:
                    attrs = json.loads(json_str)
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"Warning: attribute_descriptors JSON parse "
                          f"failed: {e}", flush=True)
                    attrs = {}

            if not attrs:
                label = ctk.CTkLabel(
                    self._attr_content,
                    text="Attribute descriptors not yet computed.",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    anchor="w",
                )
                label.pack(side="top", fill="x")
                self._attr_widgets.append(label)
                return

            # Build the ordered attribute list. Use the display order
            # list; append any extras at the end (defensive against
            # schema drift — D5).
            ordered_keys = []
            seen = set()
            for key in _ATTRIBUTE_DISPLAY_ORDER:
                if key in attrs and key not in seen:
                    ordered_keys.append(key)
                    seen.add(key)
            for key in attrs:
                if key not in seen:
                    ordered_keys.append(key)
                    seen.add(key)

            self._render_descriptor_grid(
                self._attr_content, self._attr_widgets,
                ordered_keys, attrs, _humanize_attr_name)
        except Exception as e:
            print(f"Warning: attribute profile refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Personality (20 traits, 2-col grid)
    # ------------------------------------------------------------

    def _refresh_personality(self, data):
        """Render the personality section: 20 traits, 2-col grid.

        Per D7: 2-column grid (label | descriptor). Same pattern as
        the attribute profile. The personality_descriptors JSON stores
        the descriptors DIRECTLY.
        """
        try:
            theme = get_theme()

            pers = {}
            json_str = data.get("personality_descriptors_json")
            if json_str:
                try:
                    pers = json.loads(json_str)
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"Warning: personality_descriptors JSON parse "
                          f"failed: {e}", flush=True)
                    pers = {}

            if not pers:
                label = ctk.CTkLabel(
                    self._pers_content,
                    text="Personality descriptors not yet computed.",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    anchor="w",
                )
                label.pack(side="top", fill="x")
                self._pers_widgets.append(label)
                return

            # Build the ordered trait list.
            ordered_keys = []
            seen = set()
            for key in _PERSONALITY_DISPLAY_ORDER:
                if key in pers and key not in seen:
                    ordered_keys.append(key)
                    seen.add(key)
            for key in pers:
                if key not in seen:
                    ordered_keys.append(key)
                    seen.add(key)

            self._render_descriptor_grid(
                self._pers_content, self._pers_widgets,
                ordered_keys, pers, _humanize_trait_name)
        except Exception as e:
            print(f"Warning: personality refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Descriptor grid renderer (shared by attrs + personality)
    # ------------------------------------------------------------

    def _render_descriptor_grid(self, parent, widget_list, keys, descriptors,
                                 name_humanizer):
        """Render a 2-column grid of (label | descriptor) rows.

        Shared by _refresh_attribute_profile + _refresh_personality
        since both use the same layout. Each cell shows the
        humanized name (gold, caption) + the voice descriptor
        (text_primary, body). 2 columns means 2 cells per row,
        so len(keys) / 2 rows.

        Args:
            parent: the CTkFrame to render into.
            widget_list: the instance list to track the created
                widgets (so _destroy_dynamic_widgets can clear them).
            keys: ordered list of descriptor keys to render.
            descriptors: dict of {key: descriptor_str}.
            name_humanizer: callable that converts a snake_case key
                to a human-readable label (e.g.,
                _humanize_attr_name, _humanize_trait_name).
        """
        theme = get_theme()

        # Configure the parent as a 2-column grid.
        parent.grid_columnconfigure(0, weight=1, uniform="desc")
        parent.grid_columnconfigure(1, weight=1, uniform="desc")

        # Render each key as a cell in the grid. 2 cells per row.
        for i, key in enumerate(keys):
            row = i // 2
            col = i % 2

            cell = ctk.CTkFrame(parent, fg_color="transparent")
            cell.grid(row=row, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 6, 6 if col == 0 else 0),
                      pady=2)

            # Label (humanized name) — gold caption
            label_text = name_humanizer(key)
            lbl = ctk.CTkLabel(
                cell, text=label_text,
                font=theme.fonts.caption,
                text_color=theme.colors.gold,
                anchor="w",
            )
            lbl.pack(side="top", fill="x")
            widget_list.append(lbl)

            # Descriptor (voice phrase) — body text
            descriptor = descriptors.get(key, "(uncached)")
            val = ctk.CTkLabel(
                cell, text=descriptor,
                font=theme.fonts.descriptor,
                text_color=theme.colors.text_primary,
                anchor="w", wraplength=300, justify="left",
            )
            val.pack(side="top", fill="x")
            widget_list.append(val)

            widget_list.append(cell)
