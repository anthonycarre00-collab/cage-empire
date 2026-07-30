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
from pathlib import Path

import customtkinter as ctk

# PIL is used for portrait image loading + placeholder generation
# (UI-POLISH Fix 4). Falls back gracefully if PIL isn't installed.
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from ui.theme import get_theme
from ui.state import get_state
from ui.voice_display import title_case_phrase, display_phrase, \
    display_attr_descriptor

# Phase 4 — Performance: portrait LRU cache. The Fighter Profile
# screen re-loads the same fighter's portrait on every refresh
# (Advance Day, navigation back-and-forth, theme toggle). With the
# cache, the second+ load of the same fighter_id returns the cached
# CTkImage instantly — no PIL.Image.open, no LANCZOS resize.
from ui.perf import get_cached_portrait, cache_portrait

# Voice-phrase decoder — single source of truth for the "label||phrase"
# storage format used by every interpretation engine (mirrors
# DashboardScreen's D4).
from interpretation.context_engine import (
    decode_phrase,
    compute_trajectory_for_fighter,
    get_trajectory_phrase,
    get_trajectory_phrase_ext,
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

# Per UI-POLISH Fix 1: how many attributes to show by default (the
# "top N" by raw value). The rest are hidden behind the "Show Full
# Stats" toggle. 6 is a good balance — enough to characterise a
# fighter (their 2-3 strengths + 2-3 supporting traits) without
# overwhelming the screen.
_TOP_ATTRIBUTES_COUNT = 6

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

# Per UI-POLISH Fix 1: the 5 key personality traits shown by default.
# The brief specifies "aggression, composure, discipline,
# marketability, fan_friendliness" — but marketability +
# fan_friendliness are NOT in fighter_personality (they're in
# fighters table) and therefore NOT in the personality_descriptors
# JSON. We substitute with the closest semantic equivalents that ARE
# in the cache (D3 — see worklog):
#   marketability    → charisma (public-facing magnetism)
#   fan_friendliness → sportsmanship (how fans perceive conduct)
_KEY_PERSONALITY_TRAITS = [
    "aggression", "composure", "discipline",
    "charisma", "sportsmanship",
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
# HELPERS — portrait loading (UI-POLISH Fix 4)
# ============================================================

# Path to the data/portraits/ directory. Portrait files are named
# <fighter_id>.png (e.g., data/portraits/724.png). The directory is
# at the project root (cage_empire/data/portraits/).
_PORTRAITS_DIR = (Path(__file__).resolve().parent.parent.parent.parent
                  / "data" / "portraits")

# Portrait display size (px). Per the brief: "200x200px placeholder
# at the top-left of the profile".
# UI Fix Plan 2 — Phase 3, Fix 15 (AD-7): bumped from 200 to 256.
# 256 is power-of-2 (clean downsample from 512×512 source), reuses
# across screens (256 hero / 64 watch card / 32 table thumbnail),
# and gives the portrait more visual weight on the profile (the
# profile is the hero screen for a fighter — the portrait should
# feel prominent, not tucked away).
_PORTRAIT_SIZE = 256

# Palette for the initials-placeholder background. Picked from the
# Office Mode palette so the placeholders feel branded. The fighter_id
# selects the color deterministically (so the same fighter always
# gets the same placeholder color).
_PLACEHOLDER_COLORS = [
    "#c8323a",  # crimson
    "#d4a55a",  # gold
    "#6b7280",  # steel
    "#4ade80",  # success
    "#fbbf24",  # warning
    "#3b82f6",  # blue (rare — used for variety)
]


def _center_crop_square(img):
    """Crop a PIL image to a centered square (UI Fix Plan 2, Fix 15).

    Takes the min(width, height) as the square side + crops the
    center. Used before resize so non-square source portraits
    (e.g., 512×600 uploads) aren't distorted when resized to the
    square _PORTRAIT_SIZE.

    Defensive — returns the original image on any error (so a bad
    crop doesn't prevent the portrait from rendering at all).
    """
    try:
        w, h = img.size
        if w == h:
            return img  # already square — no crop needed
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        return img.crop((left, top, left + side, top + side))
    except Exception:
        return img


def _load_portrait_image(fighter_id, first_name, last_name):
    """Load a fighter's portrait image, or generate a placeholder.

    Per UI-POLISH Fix 4: if `data/portraits/<fighter_id>.png` exists,
    load it with PIL + resize to 200x200. If no portrait exists,
    generate a placeholder image: a colored square with the fighter's
    initials (e.g., "JR" for John Reed). The color is derived from
    the fighter_id (deterministic).

    UI Fix Plan 2 — Phase 3, Fix 15 (AD-7): portrait size bumped
    from 200 to 256 + center-crop added before resize (so non-square
    source images aren't distorted). Returns a PIL.Image (ready to
    be wrapped in CTkImage), or None if PIL isn't available.
    """
    if not HAS_PIL:
        return None

    # Try to load the fighter's portrait file.
    portrait_path = _PORTRAITS_DIR / f"{fighter_id}.png"
    if portrait_path.exists():
        try:
            img = Image.open(str(portrait_path))
            img = img.convert("RGBA")
            # UI Fix Plan 2 — Phase 3, Fix 15 (AD-7): center-crop
            # before resize. Non-square source images (e.g., 512×600
            # uploads) would be squashed by a direct resize — we
            # crop the center square first so the portrait isn't
            # distorted. The crop is min(width, height) × min(width,
            # height) centered on the image's midpoint.
            img = _center_crop_square(img)
            img = img.resize((_PORTRAIT_SIZE, _PORTRAIT_SIZE),
                             Image.LANCZOS)
            return img
        except Exception as e:
            print(f"Warning: portrait load failed for fighter "
                  f"{fighter_id}: {e}", flush=True)

    # No portrait file (or load failed) — generate a placeholder.
    return _generate_initials_placeholder(fighter_id, first_name, last_name)


def _generate_initials_placeholder(fighter_id, first_name, last_name):
    """Generate a colored placeholder image with the fighter's initials.

    The placeholder is a 200x200 RGBA image with:
      - A solid color background (deterministic from fighter_id).
      - The fighter's initials centered in white, large font.

    Args:
        fighter_id: int — used to pick the background color.
        first_name, last_name: strings — used to compute initials.

    Returns:
        PIL.Image, or None if PIL isn't available.
    """
    if not HAS_PIL:
        return None

    # Pick the background color deterministically.
    color = _PLACEHOLDER_COLORS[fighter_id % len(_PLACEHOLDER_COLORS)]

    # Create the image with the colored background.
    img = Image.new("RGBA", (_PORTRAIT_SIZE, _PORTRAIT_SIZE), color)
    draw = ImageDraw.Draw(img)

    # Compute initials (e.g., "John" "Reed" → "JR").
    initials = ""
    if first_name:
        initials += str(first_name)[0].upper()
    if last_name:
        initials += str(last_name)[0].upper()
    if not initials:
        initials = "?"

    # Try to load a bundled font for the initials. Fall back to the
    # default bitmap font if none load.
    font_size = 80
    font = None
    try:
        from ui.theme import FONT_INTER_BOLD
        if FONT_INTER_BOLD.exists():
            font = ImageFont.truetype(str(FONT_INTER_BOLD), font_size)
    except Exception:
        pass
    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

    # Center the initials in the image.
    try:
        # textbbox returns (left, top, right, bottom) in pixels.
        bbox = draw.textbbox((0, 0), initials, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (_PORTRAIT_SIZE - text_w) // 2 - bbox[0]
        y = (_PORTRAIT_SIZE - text_h) // 2 - bbox[1]
        draw.text((x, y), initials, fill="white", font=font)
    except Exception:
        # Last-resort: just draw the initials at a fixed position.
        draw.text((60, 60), initials, fill="white", font=font)

    return img


# ============================================================
# HELPERS — scouting report (UI-POLISH Fix 1)
# ============================================================

def _confidence_band(confidence):
    """Translate a scout_confidence (0-100) to a voice phrase.

    Per §14: no raw attribute values in the player-facing UI. The
    scout_confidence is a raw number — band it into a voice phrase.
    """
    try:
        v = int(confidence)
    except (TypeError, ValueError):
        return "Unknown"
    if v >= 80:
        return "High Confidence"
    if v >= 60:
        return "Moderate Confidence"
    if v >= 40:
        return "Mixed Confidence"
    if v >= 20:
        return "Low Confidence"
    return "Very Low Confidence"


# ============================================================
# HELPERS — attribute ranking (UI-POLISH Fix 1, D1 carve-out)
# ============================================================

def _rank_attributes_by_value(conn, fighter_id):
    """Return attribute names sorted by raw value (descending).

    Per UI-POLISH Fix 1 D1 (§17 carve-out): reads `fighter_attributes`
    for the SOLE PURPOSE of ranking attributes by value. The raw
    values themselves are NEVER displayed — only the voice descriptors
    from the cache's attribute_descriptors JSON. This is a
    transitional pattern; a future task should add a
    `top_attribute_keys` JSON column to fighter_descriptors so the UI
    doesn't need to touch the simulation table at all.

    Returns:
        List of attribute names (strings), highest value first.
        Empty list if the fighter has no attributes row.
    """
    try:
        # Read all attribute columns + their values for this fighter.
        row = conn.execute(
            "SELECT * FROM fighter_attributes WHERE fighter_id = ?",
            (fighter_id,),
        ).fetchone()
        if row is None:
            return []
        cols = [d[0] for d in conn.execute(
            "SELECT * FROM fighter_attributes WHERE fighter_id = ?",
            (fighter_id,),
        ).description]
        # Build {attr_name: value} excluding the non-attribute columns.
        skip = {"fighter_attribute_id", "fighter_id",
                "created_at", "updated_at"}
        attrs = {col: val for col, val in zip(cols, row)
                 if col not in skip and val is not None}
        # Sort by value descending. Return the names only.
        sorted_names = sorted(attrs.keys(),
                              key=lambda k: attrs[k],
                              reverse=True)
        return sorted_names
    except sqlite3.Error as e:
        print(f"Warning: attribute ranking query failed for "
              f"fighter {fighter_id}: {e}", flush=True)
        return []


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

        # Per UI-POLISH Fix 1: "Show Full Stats" toggle state. Default
        # OFF (show only top 6 attributes + 5 key personality traits).
        # Reset to OFF whenever set_fighter_id is called (so switching
        # fighters doesn't inherit the toggle state).
        self._show_full_stats = False

        # Per UI-POLISH Fix 4: portrait image reference. Kept as an
        # attribute so the GC doesn't drop the underlying Tk image
        # (Tk images are referenced by name, not Python refcount).
        self._portrait_ctk_image = None
        self._portrait_label = None

        # Dynamic-widget tracking. _refresh destroys these before
        # re-rendering. See D10.
        self._header_widgets = []
        self._identity_widgets = []
        self._bio_widgets = []
        self._career_widgets = []
        self._fights_widgets = []
        self._attr_widgets = []
        self._pers_widgets = []
        # Per UI-POLISH Fix 1: scouting report section widgets.
        self._scouting_widgets = []

        # Scrollable root container (D4). Holds all the cards.
        self._scroll = None
        # Header labels (name + subtitle) — kept as attributes so
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
        # Per UI-POLISH Fix 1: scouting section content container.
        self._scouting_content = None
        # Per UI-POLISH Fix 1: attribute + personality section cards
        # (so we can hide/show them based on whether the fighter is
        # on the player's promotion).
        self._attr_card = None
        self._pers_card = None
        self._scouting_card = None
        # Per UI-POLISH Fix 1: the "Show Full Stats" toggle button.
        self._toggle_button = None

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
        # Per UI-POLISH Fix 1: scouting section (shown instead of
        # attribute/personality for other-promotion fighters).
        self._build_scouting_section()

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

        Per UI-POLISH Fix 1: resets the "Show Full Stats" toggle to
        OFF whenever a new fighter is loaded. The player starts with
        the summary view + can expand if they want details.

        Args:
            fighter_id: int — the fighter_id to display.
        """
        try:
            self._fighter_id = int(fighter_id)
        except (TypeError, ValueError):
            self._fighter_id = None
        # Reset the toggle state for the new fighter.
        self._show_full_stats = False
        # Immediate refresh so the screen is ready before navigation.
        self._refresh()

    # ============================================================
    # SECTION 0 — BACK BUTTON
    # ============================================================

    def _build_back_button(self):
        """Build the '← Back' button at the top.

        UI Fix Plan 2 — Phase 1, Fix 14 (AD-2): the button text is now
        generic ("← Back") instead of "← Back to Roster" because the
        player may have arrived from Free Agents, Dashboard, or any
        other screen with a fighter hyperlink. The handler uses
        GameState.go_back() with a fallback to the Roster if the
        back-stack is empty (e.g., the player deep-linked to a
        fighter profile at app startup).
        """
        theme = get_theme()
        back_row = ctk.CTkFrame(self, fg_color="transparent")
        back_row.pack(side="top", fill="x", padx=20, pady=(10, 0))

        back_btn = ctk.CTkButton(
            back_row, text="← Back",
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
        """Navigate back via GameState.go_back() with Roster fallback.

        UI Fix Plan 2 — Phase 1, Fix 14 (AD-2). Pops the navigation
        back-stack so the player returns to wherever they came from
        (Roster, Free Agents, Dashboard, etc.). If the stack is empty
        (e.g., the player deep-linked to a fighter profile at startup
        or the stack was cleared), falls back to set_active_screen
        ("roster") so the back button always goes SOMEWHERE sensible.

        Per the task brief: do NOT swallow exceptions — print the full
        traceback so the user can see what's wrong if it fails. This
        is the ONE place in this screen where we surface errors
        loudly instead of degrading to an empty-state: a broken Back
        button is a navigation dead-end, which is worse UX than a
        visible error.
        """
        import traceback
        try:
            state = get_state()
            prev = state.go_back()
            if prev is None:
                # Back-stack empty — fall back to Roster so the player
                # always lands somewhere navigable.
                state.set_active_screen("roster")
        except Exception:
            # Per Fix 14 brief: don't swallow — print full traceback
            # so the user can see what's wrong if it fails.
            print("ERROR: FighterProfileScreen._on_back failed:",
                  flush=True)
            traceback.print_exc()

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
        """Build the header: portrait + H1 name + WC · Promo · Gym subtitle.

        Per UI-POLISH Fix 4: the header is now a horizontal layout —
        portrait (200x200) on the left, name + subtitle on the right.
        The portrait is loaded by _refresh_header (which calls
        _load_portrait_image). If the portrait can't be loaded (PIL
        missing, file not found, placeholder generation fails), the
        portrait label is hidden + the name takes the full width.

        UI Fix Plan 2 — Phase 3, Fix 15: portrait bumped to 256×256
        + wrapped in a bordered CTkFrame. The border is gold by
        default (the brand accent for champion / title / hyperlink
        affordances) + swaps to crimson when the fighter is a
        current champion (the title is on the line — visual cue
        that this fighter holds a belt).

        Layout:
          ┌──────────┐  ┌─────────────────────────────────────┐
          │▌        ▐│  │  John Reed "Lightning"               │
          │▌ Portrait▐│  │  Lightweight · Alpha Combat · Gym X  │
          │▌  256    ▐│  │                                     │
          │▌        ▐│  │                                     │
          └──────────┘  └─────────────────────────────────────┘
        """
        theme = get_theme()

        # Horizontal container: portrait on left, name+subtitle right.
        header_row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        header_row.pack(side="top", fill="x", padx=20, pady=(10, 0))

        # ---- LEFT: Portrait (Fix 15: gold/crimson bordered frame) ----
        # The portrait_frame is a CTkFrame with border_width=2 +
        # border_color=gold. _refresh_header swaps the border to
        # crimson when the fighter is a current champion. The
        # portrait_label sits inside the frame + holds the actual
        # CTkImage.
        self._portrait_frame = ctk.CTkFrame(
            header_row,
            fg_color=theme.colors.bg_surface_elevated,
            corner_radius=8,
            border_width=2,
            border_color=theme.colors.gold,  # default; crimson if champ
            width=_PORTRAIT_SIZE + 4,  # +4 for the 2px border on each side
            height=_PORTRAIT_SIZE + 4,
        )
        self._portrait_frame.pack(side="left", padx=(0, 16), pady=(0, 10))
        self._portrait_frame.pack_propagate(False)  # respect the fixed size

        self._portrait_label = ctk.CTkLabel(
            self._portrait_frame, text="",
            width=_PORTRAIT_SIZE, height=_PORTRAIT_SIZE,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            anchor="center",
        )
        self._portrait_label.pack(expand=True)
        # The portrait image is set by _refresh_header. Until then,
        # show a placeholder text "No Image".
        self._portrait_label.configure(text="No Image",
                                        text_color=theme.colors.text_tertiary,
                                        font=theme.fonts.caption)

        # ---- RIGHT: Name + Subtitle ----
        name_subtle_container = ctk.CTkFrame(header_row, fg_color="transparent")
        name_subtle_container.pack(side="left", fill="both", expand=True,
                                    pady=(0, 10))

        # Name label (H1) — populated by _refresh.
        self._name_label = ctk.CTkLabel(
            name_subtle_container, text="No fighter selected",
            font=theme.fonts.h1, text_color=theme.colors.text_primary,
            anchor="w", wraplength=700, justify="left",
        )
        self._name_label.pack(side="top", fill="x", pady=(0, 4))

        # Subtitle — populated by _refresh. Fix 17: the gym name part
        # of the subtitle gets a small procedural gym icon next to it
        # (handled in _refresh_header via the gym_icon widget).
        self._subtitle_label = ctk.CTkLabel(
            name_subtle_container, text="",
            font=theme.fonts.body, text_color=theme.colors.text_secondary,
            anchor="w", wraplength=700, justify="left",
        )
        self._subtitle_label.pack(side="top", fill="x")

        # Container for the gym icon + gym name (Fix 17). Built by
        # _refresh_header so the icon can be regenerated per-fighter.
        self._gym_icon_label = None
        self._gym_icon_ctk_image = None

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

        UI Fix Plan 2 — Phase 3, Fix 16: the card now has a 2px
        crimson left-border accent (a thin CTkFrame packed left
        inside the card). The accent reads as a visual flag — the
        identity block is the fighter's "story summary" and the
        crimson bar makes it pop above the other cards.
        """
        theme = get_theme()

        # Card container. Fix 16: the card is a horizontal layout —
        # crimson accent bar (left) + content (right).
        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface,
            corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Crimson accent bar (Fix 16). 3px wide, spans the full card
        # height. Mirrors the Dashboard's Top Story crimson accent.
        accent_bar = ctk.CTkFrame(
            card, fg_color=theme.colors.crimson,
            corner_radius=0, width=3,
        )
        accent_bar.pack(side="left", fill="y")

        # Main content (sits to the right of the accent bar).
        identity_main = ctk.CTkFrame(card, fg_color="transparent")
        identity_main.pack(side="left", fill="both", expand=True)

        title = ctk.CTkLabel(
            identity_main, text="IDENTITY",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        # Content container — populated by _refresh as a 2-col grid.
        self._identity_content = ctk.CTkFrame(identity_main, fg_color="transparent")
        self._identity_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 4 — BIO
    # ============================================================

    def _build_bio_section(self):
        """Build the bio section: bio_text from fighter_bios.

        UI Fix Plan 2 — Phase 3, Fix 16: section title renamed from
        "── BIO ──" to plain "Bio" (drops the ── decoration per the
        Voice Recommendations table — modern journalistic style
        doesn't use the ASCII divider).
        """
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="Bio",
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
        """Build the career section: record + streaks + reigns + champ.

        UI Fix Plan 2 — Phase 3, Fix 16: section title renamed from
        "── CAREER ──" to plain "Career".
        """
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="Career",
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
        """Build the recent fights section: last 5 fight_history rows.

        UI Fix Plan 2 — Phase 3, Fix 16: section title renamed from
        "── RECENT FIGHTS ──" to plain "Recent Fights".
        """
        theme = get_theme()

        card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            card, text="Recent Fights",
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
        """Build the attribute profile card: 2-col grid + toggle button.

        Per D7: rendered as a 2-column grid (label | descriptor).
        Per UI-POLISH Fix 1: shows top 6 attributes by default (D1
        carve-out for ranking via fighter_attributes). The "Show Full
        Stats" toggle button reveals all 26. The toggle is at the
        top-right of the card title row.

        The card reference is kept as self._attr_card so _refresh can
        hide/show it based on whether the fighter is on the player's
        promotion (Fix 1 — other-promotion fighters see a scouting
        report instead).
        """
        theme = get_theme()

        self._attr_card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        self._attr_card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        # Title row: H2 title on the left, toggle button on the right.
        title_row = ctk.CTkFrame(self._attr_card, fg_color="transparent")
        title_row.pack(side="top", fill="x", padx=15, pady=(12, 5))

        title = ctk.CTkLabel(
            title_row, text="ATTRIBUTE PROFILE",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="left")

        # Toggle button (UI-POLISH Fix 1). Default text: "Show Full
        # Stats". When clicked, flips to "Hide Full Stats" + re-renders.
        self._toggle_button = ctk.CTkButton(
            title_row, text="▸ Show Full Stats",
            font=theme.fonts.body_small,
            width=160, height=28,
            corner_radius=6,
            fg_color=theme.colors.bg_surface_elevated,
            hover_color=theme.colors.steel,
            text_color=theme.colors.text_primary,
            command=self._on_toggle_full_stats,
        )
        self._toggle_button.pack(side="right")

        self._attr_content = ctk.CTkFrame(self._attr_card, fg_color="transparent")
        self._attr_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 8 — PERSONALITY (20 traits, 2-col grid)
    # ============================================================

    def _build_personality(self):
        """Build the personality card: 2-col grid.

        Per D7: rendered as a 2-column grid (label | descriptor).
        Per UI-POLISH Fix 1: shows 5 key traits (aggression, composure,
        discipline, charisma, sportsmanship) by default; the rest are
        revealed by the SAME "Show Full Stats" toggle in the attribute
        profile section (D3 — substituted marketability → charisma,
        fan_friendliness → sportsmanship since the former aren't in
        the personality_descriptors cache).

        The card reference is kept as self._pers_card so _refresh can
        hide/show it for other-promotion fighters.
        """
        theme = get_theme()

        self._pers_card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        self._pers_card.pack(side="top", fill="x", padx=20, pady=(0, 10))

        title = ctk.CTkLabel(
            self._pers_card, text="PERSONALITY",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._pers_content = ctk.CTkFrame(self._pers_card, fg_color="transparent")
        self._pers_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

    # ============================================================
    # SECTION 9 — SCOUTING REPORT (UI-POLISH Fix 1)
    # ============================================================

    def _build_scouting_section(self):
        """Build the scouting report card (UI-POLISH Fix 1).

        Shown INSTEAD of the attribute + personality cards for
        fighters NOT on the player's promotion (other-promotion
        fighters + free agents). Per the brief:
          - If a scouting report exists, show the scout's estimates
            (with uncertainty).
          - If no scouting report exists, show "No scouting data
            available — assign a scout to evaluate this fighter".

        The card is built hidden (pack_forget) — _refresh decides
        whether to show it based on the fighter's promotion.
        """
        theme = get_theme()

        self._scouting_card = ctk.CTkFrame(
            self._scroll, fg_color=theme.colors.bg_surface, corner_radius=8,
        )
        # NOT packed here — _refresh shows/hides it based on the
        # fighter's promotion.

        title = ctk.CTkLabel(
            self._scouting_card, text="SCOUTING REPORT",
            font=theme.fonts.h2, text_color=theme.colors.gold,
            anchor="w",
        )
        title.pack(side="top", fill="x", padx=15, pady=(12, 5))

        self._scouting_content = ctk.CTkFrame(
            self._scouting_card, fg_color="transparent")
        self._scouting_content.pack(side="top", fill="x", padx=15, pady=(0, 12))

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

            # Per UI-POLISH Fix 1: determine if this fighter is on the
            # player's promotion. If yes → show full attribute +
            # personality profile. If no → hide them + show the
            # scouting report instead.
            player_promo_id = state.get_player_promotion_id()
            is_own_fighter = (data.get("current_promotion_id") is not None
                              and data["current_promotion_id"] == player_promo_id)

            # Render every section.
            self._refresh_header(conn, data)
            self._refresh_identity(conn, data)
            self._refresh_bio(data)
            self._refresh_career(conn, data)
            self._refresh_recent_fights(conn, data)
            if is_own_fighter:
                # Own fighter — show attribute + personality profile.
                self._show_attribute_profile()
                self._hide_scouting_profile()
                self._refresh_attribute_profile(conn, data)
                self._refresh_personality(data)
            else:
                # Other promotion's fighter — hide attribute +
                # personality, show scouting report instead.
                self._hide_attribute_profile()
                self._hide_personality_profile()
                self._show_scouting_profile()
                self._refresh_scouting(conn, data)
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
            self._pers_widgets, self._scouting_widgets,
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

    def _refresh_header(self, conn, data):
        """Render the H1 name + 'WC · Promo · Gym' subtitle + portrait.

        Per UI-POLISH Fix 4: loads the fighter's portrait image (from
        data/portraits/<fighter_id>.png) or generates a placeholder
        with the fighter's initials. The portrait is set on
        self._portrait_label.

        UI Fix Plan 2 — Phase 3, Fix 15: swaps the portrait frame's
        border to crimson when the fighter is a current champion
        (visual cue that they hold a belt). Fix 17: prepends a
        procedural gym icon to the gym-name part of the subtitle.
        """
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
            # component is skipped. Fix 17: the gym name is preceded
            # by a small procedural gym icon (handled separately below
            # via _refresh_gym_icon — the subtitle text itself stays
            # plain text since CTkLabel can't host an inline image).
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

            # ---- Portrait (UI-POLISH Fix 4 + Phase 3 Fix 15) ----
            # Phase 4 — Performance: check the LRU cache first. The
            # cache stores the already-built CTkImage (not the PIL
            # image) so a cache hit skips both the file open + the
            # LANCZOS resize + the CTkImage construction. On a cache
            # miss, fall through to _load_portrait_image + cache the
            # built CTkImage for next time. The cache is bounded at
            # 200 entries (LRU eviction) so it doesn't grow without
            # limit on long sessions.
            fighter_id = data["fighter_id"]
            try:
                cached_img = get_cached_portrait(fighter_id)
                if cached_img is not None:
                    self._portrait_ctk_image = cached_img
                    self._portrait_label.configure(
                        image=self._portrait_ctk_image, text="")
                else:
                    pil_img = _load_portrait_image(
                        fighter_id,
                        data.get("first_name"),
                        data.get("last_name"),
                    )
                    if pil_img is not None:
                        self._portrait_ctk_image = ctk.CTkImage(
                            light_image=pil_img, dark_image=pil_img,
                            size=(_PORTRAIT_SIZE, _PORTRAIT_SIZE),
                        )
                        # Store in the cache for next time.
                        cache_portrait(fighter_id, self._portrait_ctk_image)
                        self._portrait_label.configure(
                            image=self._portrait_ctk_image, text="")
                    else:
                        # PIL not available — show a text placeholder.
                        self._portrait_label.configure(
                            image=None, text="?",
                            font=theme.fonts.display,
                            text_color=theme.colors.text_secondary,
                        )
            except Exception as e:
                print(f"Warning: portrait display failed for "
                      f"fighter {data['fighter_id']}: {e}", flush=True)
                self._portrait_label.configure(
                    image=None, text="?",
                    font=theme.fonts.display,
                    text_color=theme.colors.text_secondary,
                )

            # ---- Fix 15: portrait border color (gold → crimson if champ) ----
            # The champion check queries the titles table for this
            # fighter. Mirrors the check in _refresh_career (D9).
            is_champion = False
            try:
                champ_row = conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM titles WHERE "
                    "current_champion_fighter_id=? AND is_vacant=0)",
                    (data["fighter_id"],),
                ).fetchone()
                is_champion = bool(champ_row and champ_row[0] == 1)
            except sqlite3.Error:
                pass
            try:
                if is_champion:
                    self._portrait_frame.configure(
                        border_color=theme.colors.crimson)
                else:
                    self._portrait_frame.configure(
                        border_color=theme.colors.gold)
            except Exception:
                pass

            # ---- Fix 17: gym icon next to gym name ----
            # The gym icon is set as a small CTkImage on the subtitle
            # label's compound side. CTkLabel supports an `image`
            # parameter that renders the image to the left of the text
            # (with compound="left"). The icon is procedural (per
            # gym_icon.get_gym_icon) — deterministic color from gym_id
            # hash + white initials.
            self._refresh_gym_icon(data)
        except Exception as e:
            print(f"Warning: header refresh failed: {e}", flush=True)

    def _refresh_gym_icon(self, data):
        """Set a procedural gym icon on the subtitle label (Fix 17).

        Uses ui.widgets.gym_icon.get_gym_icon to generate a 20x20
        octagonal icon with the gym's initials + a deterministic
        color. Sets it as the subtitle label's `image` with
        compound="left" so it renders inline with the WC · Promo ·
        Gym text.

        Defensive — if PIL isn't installed or the gym_id is missing,
        the icon is cleared (the subtitle text remains, just without
        the icon prefix).
        """
        try:
            gym_id = data.get("current_gym_id")
            gym_name = data.get("gym_name")
            if gym_id is None or not gym_name:
                # No gym — clear any previously-set icon.
                self._subtitle_label.configure(image=None)
                self._gym_icon_ctk_image = None
                return
            try:
                from ui.widgets.gym_icon import get_gym_icon
                icon = get_gym_icon(gym_id, gym_name, size=20)
            except Exception:
                icon = None
            if icon is not None:
                self._gym_icon_ctk_image = icon
                self._subtitle_label.configure(
                    image=icon, compound="left")
            else:
                # PIL not available — clear the icon.
                self._subtitle_label.configure(image=None)
                self._gym_icon_ctk_image = None
        except Exception as e:
            print(f"Warning: gym icon refresh failed: {e}", flush=True)

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
                    # UI Fix Plan 2 — Phase 3, Fix 19: use the EXTENDED
                    # picker (8 variants) so the player sees the modern
                    # MMA journalism voice on the trajectory phrase too.
                    trajectory_phrase = get_trajectory_phrase_ext(
                        trajectory_label, rng)
            except Exception as e:
                print(f"Warning: trajectory computation failed: {e}",
                      flush=True)

            # Build the 6 phrase rows. Each is (LABEL, phrase).
            # Per UI-POLISH Fix 5: title-case the voice phrases via
            # display_phrase (handles "label||phrase" decode + title
            # case in one call).
            rows = [
                ("CAREER PHASE",
                 display_phrase(data["career_phase_stored"], "(Uncached)")),
                ("MOMENTUM",
                 display_phrase(data["momentum_stored"], "(Uncached)")),
                ("PRESSURE",
                 display_phrase(data["pressure_stored"], "(Uncached)")),
                ("NARRATIVE",
                 display_phrase(data["narrative_stored"], "(None)")),
                ("LEGACY",
                 display_phrase(data["legacy_stored"], "(Uncached)")),
                ("TRAJECTORY", title_case_phrase(trajectory_phrase)),
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
            # UI Fix Plan 2 — Phase 3, Fix 16: the badge is now BIG
            # — H2 font, full-width, gold background, ~60px tall. It
            # reads as a marquee banner at the top of the career
            # section (the most important fact about the fighter).
            if is_champion:
                for title_id, wc_name, promo_name in champion_titles:
                    badge = ctk.CTkLabel(
                        self._career_content,
                        text=f"★ CHAMPION — {wc_name} ({promo_name})",
                        font=theme.fonts.h2,
                        text_color=theme.colors.bg_base,
                        fg_color=theme.colors.gold,
                        corner_radius=6,
                        height=60,
                        anchor="center",
                    )
                    badge.pack(side="top", fill="x", pady=(0, 8))
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

        UI Fix Plan 2 — Phase 3, Fix 16: each fight is now its own
        row card with bg_surface_elevated (was a transparent row
        inside the parent card). The W/L badge is a 24×24 colored
        CIRCLE (was a text label " W " — the new circle reads as a
        proper outcome badge like a sports app). Colors: gold for
        Win, crimson for Loss, steel for Draw.
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
                # Fix 16: each fight is its own row card with
                # bg_surface_elevated + a subtle border. Reads as a
                # discrete fight entry (vs. the old transparent row
                # which blended into the parent card).
                row_card = ctk.CTkFrame(
                    self._fights_content,
                    fg_color=theme.colors.bg_surface_elevated,
                    corner_radius=6,
                )
                row_card.pack(side="top", fill="x", pady=3, padx=2)

                # Inner padding frame so the badge + labels don't
                # touch the card border.
                inner = ctk.CTkFrame(row_card, fg_color="transparent")
                inner.pack(side="top", fill="x", padx=10, pady=6)

                # Outcome badge (W/L/D) — Fix 16: 24×24 colored circle.
                # Implemented as a CTkLabel with the badge color as
                # fg_color + corner_radius=12 (half of 24 = full circle).
                # The badge text (W/L/D) is rendered in the bg_base
                # color so it's high-contrast against the colored circle.
                badge_text, badge_color = _outcome_badge(outcome)
                badge = ctk.CTkLabel(
                    inner, text=badge_text,
                    font=(theme.fonts.body_small[0],
                          theme.fonts.body_small[1], "bold"),
                    text_color=theme.colors.bg_base,
                    fg_color=badge_color,
                    corner_radius=12,
                    width=24, height=24,
                )
                badge.pack(side="left", padx=(0, 10))
                self._fights_widgets.append(badge)

                # Opponent name
                opp_name = _format_name(opp_first, opp_last, opp_nick)
                opp_label = ctk.CTkLabel(
                    inner, text=f"vs {opp_name}",
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
                    inner, text=f"({result_label_str})",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_secondary,
                    anchor="w",
                )
                result_label.pack(side="left", padx=(0, 8))
                self._fights_widgets.append(result_label)

                # Title at stake marker
                if title_at_stake:
                    title_marker = ctk.CTkLabel(
                        inner, text="★ TITLE",
                        font=theme.fonts.caption,
                        text_color=theme.colors.gold,
                        anchor="w",
                    )
                    title_marker.pack(side="left", padx=(0, 8))
                    self._fights_widgets.append(title_marker)

                # Date (right-aligned)
                date_str = str(event_date)[:10] if event_date else ""
                date_label = ctk.CTkLabel(
                    inner, text=f"· {date_str}",
                    font=theme.fonts.caption,
                    text_color=theme.colors.text_tertiary,
                    anchor="e",
                )
                date_label.pack(side="right")
                self._fights_widgets.append(date_label)

                self._fights_widgets.append(row_card)
                self._fights_widgets.append(inner)
        except Exception as e:
            print(f"Warning: recent fights refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Attribute profile (26 attributes, 2-col grid)
    # ------------------------------------------------------------

    def _refresh_attribute_profile(self, conn, data):
        """Render the attribute profile card.

        Per UI-POLISH Fix 1:
          - Default view: top _TOP_ATTRIBUTES_COUNT (6) attributes by
            raw value, displayed as voice descriptors.
          - "Show Full Stats" toggle reveals all 26 attributes.
          - The ranking is computed via _rank_attributes_by_value
            (D1 carve-out — reads fighter_attributes for SORTING ONLY;
            the displayed values are voice descriptors from the
            attribute_descriptors JSON cache, never raw numbers).
        Per UI-POLISH Fix 5: descriptors are title-cased via
          display_attr_descriptor so they read as polished prose.

        Per D7: 2-column grid (label | descriptor). The
        attribute_descriptors JSON stores descriptors DIRECTLY (no
        "||" prefix) — voice.py already applied describe_attribute.
        """
        try:
            theme = get_theme()

            # Update the toggle button text based on the current state.
            if self._toggle_button is not None:
                if self._show_full_stats:
                    self._toggle_button.configure(text="▴ Hide Full Stats")
                else:
                    self._toggle_button.configure(text="▸ Show Full Stats")

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

            # Build the ordered attribute list. Per UI-POLISH Fix 1:
            # when the toggle is OFF, show the top N attributes by
            # raw value (using _rank_attributes_by_value — D1 carve-
            # out for ranking only). When ON, show ALL attributes in
            # the canonical display order.
            if self._show_full_stats:
                # Full stats — use the canonical display order.
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
            else:
                # Summary view — top N by raw value. Get the ranking
                # from fighter_attributes (D1 carve-out), then filter
                # to those that have descriptors in the JSON cache.
                ranked = _rank_attributes_by_value(conn, data["fighter_id"])
                ordered_keys = [k for k in ranked if k in attrs][:_TOP_ATTRIBUTES_COUNT]
                # If ranking failed (empty), fall back to the first
                # N from the canonical display order.
                if not ordered_keys:
                    for key in _ATTRIBUTE_DISPLAY_ORDER:
                        if key in attrs:
                            ordered_keys.append(key)
                        if len(ordered_keys) >= _TOP_ATTRIBUTES_COUNT:
                            break

            self._render_descriptor_grid(
                self._attr_content, self._attr_widgets,
                ordered_keys, attrs, _humanize_attr_name,
                title_case=True)
        except Exception as e:
            print(f"Warning: attribute profile refresh failed: {e}",
                  flush=True)

    # ------------------------------------------------------------
    # Personality (20 traits, 2-col grid)
    # ------------------------------------------------------------

    def _refresh_personality(self, data):
        """Render the personality card.

        Per UI-POLISH Fix 1:
          - Default view: 5 key traits (aggression, composure,
            discipline, charisma, sportsmanship — D3 substitutes for
            the brief's marketability/fan_friendliness which aren't
            in the personality_descriptors cache).
          - "Show Full Stats" toggle reveals all 20 traits.
        Per UI-POLISH Fix 5: descriptors are title-cased via
          display_attr_descriptor.

        Per D7: 2-column grid (label | descriptor). Same pattern as
        the attribute profile.
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

            # Build the ordered trait list. Per UI-POLISH Fix 1:
            # when the toggle is OFF, show only the 5 key traits.
            # When ON, show ALL traits in canonical display order.
            if self._show_full_stats:
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
            else:
                # Summary view — 5 key traits in the brief's order.
                ordered_keys = [k for k in _KEY_PERSONALITY_TRAITS
                                if k in pers]
                # If none of the key traits are in the cache (shouldn't
                # happen, but defensive), fall back to the first 5
                # from the canonical display order.
                if not ordered_keys:
                    for key in _PERSONALITY_DISPLAY_ORDER:
                        if key in pers:
                            ordered_keys.append(key)
                        if len(ordered_keys) >= 5:
                            break

            self._render_descriptor_grid(
                self._pers_content, self._pers_widgets,
                ordered_keys, pers, _humanize_trait_name,
                title_case=True)
        except Exception as e:
            print(f"Warning: personality refresh failed: {e}", flush=True)

    # ------------------------------------------------------------
    # Descriptor grid renderer (shared by attrs + personality)
    # ------------------------------------------------------------

    def _render_descriptor_grid(self, parent, widget_list, keys, descriptors,
                                 name_humanizer, title_case=False):
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
            title_case: if True (UI-POLISH Fix 5), apply
                display_attr_descriptor to the descriptor string so
                it reads as polished Title Case prose rather than
                lowercase voice.py output.
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

            # Descriptor (voice phrase) — body text. Per UI-POLISH
            # Fix 5: title-case the descriptor so it reads as polished
            # prose. display_attr_descriptor handles None/empty + the
            # title-case transformation.
            descriptor = descriptors.get(key, "")
            if title_case:
                descriptor = display_attr_descriptor(descriptor)
            else:
                descriptor = descriptor or "(Uncached)"
            val = ctk.CTkLabel(
                cell, text=descriptor,
                font=theme.fonts.descriptor,
                text_color=theme.colors.text_primary,
                anchor="w", wraplength=300, justify="left",
            )
            val.pack(side="top", fill="x")
            widget_list.append(val)

            widget_list.append(cell)

    # ============================================================
    # UI-POLISH Fix 1 — show/hide helpers + toggle handler
    # ============================================================

    def _show_attribute_profile(self):
        """Pack the attribute profile card so it's visible."""
        try:
            if self._attr_card is not None:
                self._attr_card.pack(side="top", fill="x", padx=20,
                                     pady=(0, 10))
        except Exception:
            pass

    def _hide_attribute_profile(self):
        """Hide the attribute profile card (other-promotion fighter)."""
        try:
            if self._attr_card is not None:
                self._attr_card.pack_forget()
        except Exception:
            pass

    def _hide_personality_profile(self):
        """Hide the personality card (other-promotion fighter)."""
        try:
            if self._pers_card is not None:
                self._pers_card.pack_forget()
        except Exception:
            pass

    def _show_scouting_profile(self):
        """Pack the scouting report card so it's visible."""
        try:
            if self._scouting_card is not None:
                self._scouting_card.pack(side="top", fill="x", padx=20,
                                          pady=(0, 10))
        except Exception:
            pass

    def _hide_scouting_profile(self):
        """Hide the scouting report card (own fighter)."""
        try:
            if self._scouting_card is not None:
                self._scouting_card.pack_forget()
        except Exception:
            pass

    def _on_toggle_full_stats(self):
        """Handle "Show Full Stats" / "Hide Full Stats" button click.

        Flips self._show_full_stats + re-renders the attribute +
        personality sections. Does NOT re-query the DB (the data is
        already cached in self._roster_data... actually no, it's
        re-queried — _refresh re-queries. That's fine, the query is
        fast for a single fighter).
        """
        try:
            self._show_full_stats = not self._show_full_stats
            # Re-render. The toggle state is preserved (we just
            # flipped it). _refresh will pick up the new state.
            self._refresh()
        except Exception as e:
            print(f"Warning: toggle full stats failed: {e}", flush=True)

    # ============================================================
    # UI-POLISH Fix 1 — scouting report refresh
    # ============================================================

    def _refresh_scouting(self, conn, data):
        """Render the scouting report card for other-promotion fighters.

        Per UI-POLISH Fix 1 + the brief:
          - If a scouting_reports row exists for this fighter, show
            the scout's estimates (potential, strengths, weaknesses,
            report text, confidence as a voice band).
          - If no row exists, show "No scouting data available —
            assign a scout to evaluate this fighter".

        Reads from `scouting_reports` (a simulation table per §17.3,
        but it's NOT a fighter-attribute table — it's a scouting-
        specific table that the player explicitly commissions via the
        Scouting screen. Reading it here is a §17-adjacent carve-out
        analogous to fighter_career for record stats: the data is
        commission-by-the-player, not raw fighter simulation state.)
        """
        try:
            theme = get_theme()

            # Query the latest scouting report for this fighter.
            # ORDER BY report_date DESC LIMIT 1 — if multiple reports
            # exist, show the most recent.
            report = None
            try:
                report = conn.execute(
                    """
                    SELECT scout_id, report_date, estimated_potential,
                           estimated_ceiling, estimated_floor,
                           estimated_strengths, estimated_weaknesses,
                           marketability_assessment, injury_risk_assessment,
                           contract_cost_estimate, scout_confidence,
                           is_stale, report_text
                    FROM scouting_reports
                    WHERE target_fighter_id = ?
                    ORDER BY report_date DESC
                    LIMIT 1
                    """,
                    (data["fighter_id"],),
                ).fetchone()
            except sqlite3.Error as e:
                print(f"Warning: scouting report query failed: {e}",
                      flush=True)

            if report is None:
                # No scouting report — show the empty-state message.
                empty_label = ctk.CTkLabel(
                    self._scouting_content,
                    text="No scouting data available — assign a scout to "
                         "evaluate this fighter.",
                    font=theme.fonts.body,
                    text_color=theme.colors.text_tertiary,
                    anchor="w", wraplength=700, justify="left",
                )
                empty_label.pack(side="top", fill="x", pady=(0, 8))
                self._scouting_widgets.append(empty_label)

                # Add a hint about how to assign a scout.
                hint_label = ctk.CTkLabel(
                    self._scouting_content,
                    text="Tip: open the Scouting screen (FIGHTERS group in "
                         "the sidebar) to assign a scout to this fighter.",
                    font=theme.fonts.caption,
                    text_color=theme.colors.text_secondary,
                    anchor="w", wraplength=700, justify="left",
                )
                hint_label.pack(side="top", fill="x")
                self._scouting_widgets.append(hint_label)
                return

            # Unpack the report row.
            (scout_id, report_date, est_potential, est_ceiling, est_floor,
             est_strengths_json, est_weaknesses_json, marketability,
             injury_risk, contract_cost, scout_confidence,
             is_stale, report_text) = report

            # ---- Row 1: Confidence + date ----
            meta_row = ctk.CTkFrame(
                self._scouting_content, fg_color="transparent")
            meta_row.pack(side="top", fill="x", pady=(0, 6))
            self._scouting_widgets.append(meta_row)

            confidence_label = ctk.CTkLabel(
                meta_row,
                text=f"Scout Confidence: {_confidence_band(scout_confidence)}",
                font=theme.fonts.body,
                text_color=theme.colors.gold,
                anchor="w",
            )
            confidence_label.pack(side="left")
            self._scouting_widgets.append(confidence_label)

            if report_date:
                date_label = ctk.CTkLabel(
                    meta_row,
                    text=f"· Reported {str(report_date)[:10]}",
                    font=theme.fonts.caption,
                    text_color=theme.colors.text_tertiary,
                    anchor="e",
                )
                date_label.pack(side="right")
                self._scouting_widgets.append(date_label)

            # Stale warning
            if is_stale:
                stale_label = ctk.CTkLabel(
                    self._scouting_content,
                    text="⚠ This report is stale — the fighter may have "
                         "changed since it was filed.",
                    font=theme.fonts.caption,
                    text_color=theme.colors.warning,
                    anchor="w", wraplength=700, justify="left",
                )
                stale_label.pack(side="top", fill="x", pady=(0, 6))
                self._scouting_widgets.append(stale_label)

            # ---- Row 2: Estimated potential ----
            if est_potential:
                self._render_scouting_row(
                    "Potential Estimate", title_case_phrase(est_potential))

            # ---- Row 3: Estimated strengths (JSON list) ----
            strengths = self._parse_json_list(est_strengths_json)
            if strengths:
                self._render_scouting_row(
                    "Estimated Strengths",
                    ", ".join(title_case_phrase(s) for s in strengths))

            # ---- Row 4: Estimated weaknesses ----
            weaknesses = self._parse_json_list(est_weaknesses_json)
            if weaknesses:
                self._render_scouting_row(
                    "Estimated Weaknesses",
                    ", ".join(title_case_phrase(w) for w in weaknesses))

            # ---- Row 5: Marketability + injury risk ----
            if marketability:
                self._render_scouting_row(
                    "Marketability", title_case_phrase(marketability))
            if injury_risk:
                self._render_scouting_row(
                    "Injury Risk", title_case_phrase(injury_risk))

            # ---- Row 6: Report text (the scout's narrative) ----
            if report_text:
                text_label = ctk.CTkLabel(
                    self._scouting_content,
                    text=report_text,
                    font=theme.fonts.descriptor,
                    text_color=theme.colors.text_primary,
                    anchor="w", wraplength=900, justify="left",
                )
                text_label.pack(side="top", fill="x", pady=(8, 0))
                self._scouting_widgets.append(text_label)
        except Exception as e:
            print(f"Warning: scouting refresh failed: {e}", flush=True)

    def _render_scouting_row(self, label_text, value_text):
        """Render a single label | value row in the scouting card."""
        theme = get_theme()
        row_frame = ctk.CTkFrame(
            self._scouting_content, fg_color="transparent")
        row_frame.pack(side="top", fill="x", pady=2)

        lbl = ctk.CTkLabel(
            row_frame, text=f"{label_text}:",
            font=theme.fonts.body,
            text_color=theme.colors.gold,
            anchor="w", width=180,
        )
        lbl.pack(side="left", padx=(0, 12))

        val = ctk.CTkLabel(
            row_frame, text=value_text,
            font=theme.fonts.body,
            text_color=theme.colors.text_primary,
            anchor="w", wraplength=600, justify="left",
        )
        val.pack(side="left", fill="x", expand=True)

        self._scouting_widgets.append(row_frame)

    @staticmethod
    def _parse_json_list(json_str):
        """Parse a JSON string that should be a list of strings.

        Defensive — returns [] on any parse failure (the seed scripts
        sometimes write NULL or malformed JSON for estimated_strengths
        / estimated_weaknesses).
        """
        if not json_str:
            return []
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
            return []
        except (json.JSONDecodeError, TypeError):
            return []
