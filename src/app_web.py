"""CAGE EMPIRE — pywebview desktop application entry point.

This module replaces `src/ui/app.py` (the CustomTkinter shell) with a
pywebview window wrapping the HTML/CSS/JS frontend in `src/web/`.

Architecture (per docs/UI_MIGRATION_PYWEBVIEW.md):
  - pywebview creates a native desktop window (no browser chrome)
  - Loads `src/web/index.html` (the app shell: top bar + sidebar + screen container)
  - Exposes a Python `Api` class to JS via `window.pywebview.api.<method>`
  - The frontend calls bridge methods → Python returns JSON-serializable dicts
  - All game logic (services/, interpretation/, rival_ai/, tick_processor)
    is UNCHANGED — this module is a thin UI shell + bridge

What this module does NOT do:
  - Modify the DB schema (v3.15.0 is correct)
  - Modify any game logic in src/services/, src/interpretation/, src/rival_ai/
  - Depend on CustomTkinter / tkinter for rendering (tkinter is imported
    transitively by src/app.py via tick_processor, but we never instantiate
    a Tk root — pywebview provides the window)

CONVENTIONS compliance:
  §13 — Design Law: this is the shell (infrastructure). Every pillar
        is reachable from the sidebar.
  §14 — Voice Layer: the API methods read from `fighter_descriptors`
        (the interpretation cache), NOT raw attribute tables. Voice
        phrases are returned to JS, not raw 0-100 numbers.
  §15 — Event Bus: registers ALL 17 event-bus subscribers (same as
        the old CTk app) so the simulation runs correctly on Advance
        Day. The Advance Day button calls services.clock.advance_day
        which delegates to tick_processor.run_tick which publishes
        Events.TICK_ADVANCED.

Launch:
  python src/app_web.py
"""

import sys
import os
import re
import sqlite3
import base64
import calendar
import json
import traceback
from pathlib import Path
from datetime import datetime, timedelta

# ============================================================
# PATH SETUP — make `src/` importable so `from services.clock
# import advance_day` works the same way it does in the old app.
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DB_PATH = Path(os.environ.get(
    "CAGE_EMPIRE_DB_PATH",
    str(PROJECT_DIR / "data" / "cage_empire.db")
))

WEB_DIR = BASE_DIR / "web"
INDEX_HTML = WEB_DIR / "index.html"
LOGO_DIR = BASE_DIR / "web" / "assets" / "promo_logos"


# ============================================================
# GAME LOGIC IMPORTS (after sys.path setup)
# ============================================================
from services.clock import get_clock, advance_day  # noqa: E402


# ============================================================
# EVENT-BUS REGISTRATION — identical to src/ui/app.py lines 197-302.
# Registers all 17 event-bus subscribers so the simulation runs
# correctly on Advance Day. Lazy-imported with try/except so a
# missing module doesn't crash the whole app.
# ============================================================
def register_all_subscribers():
    """Register every event-bus subscriber the game needs.

    Mirrors the registration block in src/ui/app.py:__init__ — the
    same 17 modules in the same order. The interpretation layer is
    registered LAST per CONVENTIONS §17.5 so the cache reflects the
    latest simulation state.
    """
    # Phase E1.1 (docs/ECON_STAFF_PLAN.md §0 + §1.5 bug #1) — `finance`
    # was missing from this list. Without it, every event the player
    # runs from the GUI produced zero finance_transactions rows (promo 1
    # had 1 row — the $80M opening seed — despite 431 completed events).
    # Placed between `show_rating` and `venues` so finance writes its
    # rows before reputation's bankruptcy check reads current_cash on
    # the same EVENT_COMPLETED (per reputation.py:349-360).
    registration_modules = [
        "news", "social", "rivalries", "punditry", "morale",
        "suspensions", "agent_offers", "career_arc", "rival_ai",
        "show_rating", "finance", "venues", "save_load",
        "player_settings", "reputation",
        # NEWS-FINANCE-GYM-LEGACY Issue 8 — weekly gym-transfer
        # subscriber. Registered here so the live web app processes
        # gym transfers on Advance Day.
        "gym_transfers",
    ]
    for mod_name in registration_modules:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
        except Exception as e:
            print(f"[app_web] WARN: {mod_name}.register_subscribers "
                  f"failed: {e}", flush=True)

    # services.hof_svc — Phase 1 Fix 1.4 (HoF induction on retirement)
    try:
        from services.hof_svc import register_subscribers as _reg_hof
        _reg_hof()
    except Exception as e:
        print(f"[app_web] WARN: services.hof_svc failed: {e}", flush=True)

    # services.pruning_svc — REPLAN_RESET §10 (monthly DB pruning)
    try:
        from services.pruning_svc import register_subscribers as _reg_prune
        _reg_prune()
    except Exception as e:
        print(f"[app_web] WARN: services.pruning_svc failed: {e}",
              flush=True)

    # interpretation — Phase 2 Task 2.1 (snapshot cache refresh).
    # Registered LAST per CONVENTIONS §17.5.
    try:
        from interpretation import register_subscribers as _reg_interp
        _reg_interp()
    except Exception as e:
        print(f"[app_web] WARN: interpretation failed: {e}", flush=True)

    # HW2.4 — world_health monthly subscriber. Computes + caches the
    # overall world health status (HEALTHY/DEGRADED/BROKEN) on each
    # monthly tick (current_day % 30 == 0). The result is exposed via
    # the get_world_health() API method.
    try:
        from event_bus import get_bus, Events
        from tick_processor import _world_health_monthly_subscriber
        get_bus().subscribe(
            Events.TICK_ADVANCED,
            _world_health_monthly_subscriber,
            name="world_health.monthly_check",
        )
    except Exception as e:
        print(f"[app_web] WARN: world_health subscriber registration "
              f"failed: {e}", flush=True)


# ============================================================
# HELPERS — voice-phrase decoding + formatting
# (mirror of scripts/generate_dashboard_html.py — same logic so the
#  dashboard renders identically to the approved prototype)
# ============================================================

def _decode_phrase(stored):
    """Extract the voice phrase from 'label||phrase' format."""
    if not stored or "||" not in stored:
        return stored or ""
    return stored.split("||", 1)[1]


def _decode_label(stored):
    """Extract the label from 'label||phrase' format."""
    if not stored or "||" not in stored:
        return stored or ""
    return stored.split("||", 1)[0]


def _format_cash(cash):
    if abs(cash) >= 1_000_000_000:
        return f"${cash / 1_000_000_000:.2f}B"
    if abs(cash) >= 1_000_000:
        return f"${cash / 1_000_000:.1f}M"
    if abs(cash) >= 1_000:
        return f"${cash / 1_000:.0f}K"
    return f"${cash:,.0f}"


def _reign_length(since_date, sim_date):
    try:
        since = datetime.strptime(since_date, "%Y-%m-%d")
        sim = datetime.strptime(sim_date, "%Y-%m-%d")
        months = (sim.year - since.year) * 12 + (sim.month - since.month)
        if months >= 12:
            return f"{months // 12}y {months % 12}m"
        return f"{months}m"
    except Exception:
        return "—"


def _format_long_date(date_str):
    """Format a YYYY-MM-DD string as 'Month D, YYYY' (e.g. 'March 15, 2027').

    Used for player-facing date hints (the "Your event is scheduled for
    March 15, 2027" message in resolve_next_fight, etc.). Returns the
    raw string on parse failure so the player always sees something.
    """
    if not date_str:
        return "—"
    try:
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return calendar.month_name[dt.month] + " " + str(dt.day) + ", " + str(dt.year)
    except Exception:
        return str(date_str)


def _reputation_phrase(rep):
    if rep >= 80: return "Highly Respected"
    if rep >= 60: return "Respected"
    if rep >= 40: return "Established"
    if rep >= 20: return "Emerging"
    return "Unknown"


def _fan_trust_phrase(trust):
    if trust >= 70: return "Strong"
    if trust >= 50: return "Moderate"
    if trust >= 30: return "Strained"
    return "Weak"


def _reputation_pct(rep):
    """Tier-based bar-fill pct (0-100) for the dashboard reputation meter.

    Phase 7 / Task A1 — replaces the raw 0-100 `reputation` int in
    the dashboard JSON payload (per CONVENTIONS §17.4 "Rich Not
    Thin": only voice phrases should cross the API boundary as text,
    but visualization widths are an explicit carve-out). The pct is
    banded to the same tiers as `_reputation_phrase()` so the bar
    fill visually tracks the phrase without leaking the exact int
    (e.g., a "Respected" promo (60-79) shows 75% — same band every
    time, no information loss vs. the phrase).
    """
    if rep >= 80: return 100   # Highly Respected — gold
    if rep >= 60: return 75    # Respected — gold-leaning
    if rep >= 40: return 60    # Established — steel
    if rep >= 20: return 35    # Emerging — crimson-leaning
    return 20                  # Unknown — crimson


def _fan_trust_pct(trust):
    """Tier-based bar-fill pct (0-100) for the dashboard fan-trust meter.

    Phase 7 / Task A1 — companion to `_reputation_pct()`. Same
    carve-out rationale (§17.4 visualization-width exemption).
    """
    if trust >= 70: return 100  # Strong — gold
    if trust >= 50: return 65   # Moderate — steel
    if trust >= 30: return 40   # Strained — crimson-leaning
    return 25                   # Weak — crimson


def _rating_tier(rating):
    if not rating: return ("unrated", "#6b7280")
    if rating >= 80: return ("a spectacular night of fights", "#4ade80")
    if rating >= 70: return ("a highly entertaining show", "#4ade80")
    if rating >= 60: return ("a solid night of fights", "#e0a957")
    if rating >= 50: return ("a decent show that failed to deliver", "#fbbf24")
    return ("a forgettable night for the fans", "#d63a3f")


# ============================================================
# NATION → ISO3 LOOKUP (nations table has no iso3 column —
# per SCREEN_DATA_AUDIT §2.2 / §5.5, this is the workaround)
# ============================================================
_NATION_ISO3 = {
    "United States": "USA", "Brazil": "BRA", "Japan": "JPN",
    "Russia": "RUS", "United Kingdom": "GBR", "Mexico": "MEX",
    "Canada": "CAN", "Australia": "AUS", "Ireland": "IRL",
    "Nigeria": "NGA", "France": "FRA", "Germany": "GER",
    "Poland": "POL", "Sweden": "SWE", "South Korea": "KOR",
    "China": "CHN", "Cuba": "CUB", "Argentina": "ARG",
    "Netherlands": "NED", "Dagestan": "DAG",
}


def _nation_iso3(name, nation_id=None):
    """Return a 3-letter ISO-style nation code (or 'INT' for unknown)."""
    if name and name in _NATION_ISO3:
        return _NATION_ISO3[name]
    if name and len(name) >= 3:
        return name[:3].upper()
    return "INT"


# F3 (docs/FIX_PLAN_CACHE_CASH_EB.md §3) — venue capacity-based icon.
# The user spec lists four icons:
#   arena (15k+)    → 🏟  (stadium)
#   ballroom (5-15k)→ 🏛  (grand hall — distinct from arena)
#   theater (2-5k)  → 🎭  (theater masks)
#   outdoor (<2k)   → 🌳  (outdoor / park)
# Drives the venue card's primary visual anchor in the Event Builder.
_VENUE_ICONS = {
    "arena":    "🏟",
    "ballroom": "🏛",
    "theater":  "🎭",
    "outdoor":  "🌳",
}


def _venue_icon(venue_type):
    """Return the emoji icon for a venue_type (or a fallback)."""
    return _VENUE_ICONS.get(venue_type or "ballroom", "🏛")


# F3 — nation flag emoji helper. Converts a nation name to its
# regional-indicator-symbol flag emoji (🇺🇸, 🇧🇷, …). Each flag is
# exactly 2 regional-indicator characters (one per ISO2 letter).
# Falls back to "🏳" (white flag) for unknown nations so the venue
# card always has *some* flag marker.
#
# NOTE: the existing _NATION_ISO3 map returns 3-letter codes (USA,
# BRA, …) which can't be turned into flag emojis directly (regional
# indicator pairs only take 2 letters). So we maintain an explicit
# nation-name → ISO2 map here. Add new nations as the world grows.
_NATION_ISO2 = {
    "United States": "US", "Brazil": "BR", "Japan": "JP",
    "Russia": "RU", "United Kingdom": "GB", "Mexico": "MX",
    "Canada": "CA", "Australia": "AU", "Ireland": "IE",
    "Nigeria": "NG", "France": "FR", "Germany": "DE",
    "Poland": "PL", "Sweden": "SE", "South Korea": "KR",
    "China": "CN", "Cuba": "CU", "Argentina": "AR",
    "Netherlands": "NL", "Dagestan": "RU",  # region — uses RU flag
}


def _nation_flag_emoji(name):
    if not name:
        return "🏳"
    iso2 = _NATION_ISO2.get(name)
    if not iso2 or len(iso2) != 2:
        # Fallback: try the first 2 letters of the uppercased name.
        u = name.upper()
        if len(u) >= 2 and u[:2].isalpha():
            iso2 = u[:2]
        else:
            return "🏳"
    try:
        # Regional Indicator Symbol A-Z = U+1F1E6 .. U+1F1FF
        return "".join(
            chr(0x1F1E6 + (ord(c) - ord("A"))) for c in iso2.upper()
        )
    except Exception:
        return "🏳"


# Phase E4 — skill_level → voice phrase (per docs/ECON_STAFF_PLAN.md
# §4.3.1 + task brief). NEVER returns the raw 0-100 int — only the
# voice descriptor. The bands:
#   80-100  → "world-class"
#   60-79   → "established"
#   40-59   → "promising"
#   20-39   → "unproven"
# Below 20 stays "unproven" (no separate "novice" tier — the spec
# only defines 4 tiers).
def _skill_phrase(skill_level):
    if skill_level is None:
        return "promising"
    s = int(skill_level)
    if s >= 80:
        return "world-class"
    if s >= 60:
        return "established"
    if s >= 40:
        return "promising"
    return "unproven"


# Phase E4 — staff role_type → human-readable label (per task brief).
_ROLE_LABELS = {
    "coach":           "Coach",
    "scout":           "Scout",
    "doctor":          "Doctor",
    "cutman":          "Cutman",
    "general_manager": "General Manager",
    "commentator":     "Commentator",
}


def _role_label(role_type):
    return _ROLE_LABELS.get(role_type or "", role_type or "—")


# P1-WIRE-4-SCREENS — voice phrases for the Scouting screen.
# Per docs/P1_PLAN_WIRE_SCREENS.md §3 + CONVENTIONS §14:
#   - Scout attributes (eye_for_talent / technical_analysis /
#     character_reading) are 0-100 ints — NEVER shown raw. Wrapped
#     in voice phrases.
#   - mistake_rate (0-100) is shown as a reliability phrase.
#   - scout_confidence (0-100) was DROPPED from JSON payloads in
#     Phase 7 / Task A5 (per §17.4 "Rich Not Thin"). Only the voice
#     phrase `_scout_confidence_phrase()` is sent; the UI shows
#     "HIGHLY CONFIDENT" / "MODERATELY CONFIDENT" / "UNCERTAIN" /
#     "WILD GUESS" — no raw int crosses the API boundary.
def _scout_attr_phrase(value, kind):
    """Voice phrase for a scout attribute (0-100).

    kind is 'eye' / 'tech' / 'character' — drives the noun.
    Bands:
      80-100 → "elite eye" / "elite technical eye" / "elite character read"
      60-79  → "sharp eye" / "sharp technical eye" / "sharp character read"
      40-59  → "decent eye" / "decent technical eye" / "decent character read"
      20-39  → "rough eye" / "rough technical eye" / "rough character read"
      0-19   → "untrained eye" / "untrained technical eye" / "untrained character read"
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 50
    noun_map = {
        "eye":       "eye",
        "tech":      "technical eye",
        "character": "character read",
    }
    noun = noun_map.get(kind, "eye")
    if v >= 80:
        return "elite " + noun
    if v >= 60:
        return "sharp " + noun
    if v >= 40:
        return "decent " + noun
    if v >= 20:
        return "rough " + noun
    return "untrained " + noun


def _scout_reliability_phrase(mistake_rate):
    """Voice phrase for a scout's mistake_rate (0-100, lower = better).

    Bands:
      0-9    → "sharp judgment"
      10-19  → "reliable"
      20-34  → "occasional miss"
      35+    → "wild card"
    """
    try:
        v = int(mistake_rate)
    except (TypeError, ValueError):
        v = 20
    if v <= 9:
        return "sharp judgment"
    if v <= 19:
        return "reliable"
    if v <= 34:
        return "occasional miss"
    return "wild card"


# P1-WIRE-4-SCREENS — voice phrases for the Training Camps (Gyms)
# screen. Per docs/P1_PLAN_WIRE_SCREENS.md §4 + CONVENTIONS §14:
#   - Gym stats (reputation / facility_quality / medical_support /
#     sparring_depth / development_focus / weight_cut_support — all
#     0-100) are OK to display — gym ratings, NOT fighter attrs.
#   - facility_quality gets a voice phrase wrapper ('world-class' /
#     'elite' / 'solid' / 'adequate' / 'bare-bones') per the brief.
#   - camp_morale / camp_fatigue / camp_injury_risk (0-100) are OK
#     to display — camp-state ratings, NOT fighter attributes.
#   - camp_focus is a categorical label, not a rating.
def _gym_quality_phrase(facility_quality):
    """Voice phrase for a gym's facility_quality (0-100).

    Bands (per docs/P1_PLAN_WIRE_SCREENS.md §4):
      90-100 → "world-class"
      75-89  → "elite"
      60-74  → "solid"
      40-59  → "adequate"
      0-39   → "bare-bones"
    """
    try:
        v = int(facility_quality)
    except (TypeError, ValueError):
        v = 50
    if v >= 90:
        return "world-class"
    if v >= 75:
        return "elite"
    if v >= 60:
        return "solid"
    if v >= 40:
        return "adequate"
    return "bare-bones"


_GYM_CULTURE_LABELS = {
    "predator":     "Predator",
    "loose":        "Loose",
    "disciplined":  "Disciplined",
    "balanced":     "Balanced",
}


def _gym_culture_label(tone):
    """Return a Title Case label for a gym's culture_tone."""
    if not tone:
        return "Balanced"
    return _GYM_CULTURE_LABELS.get(tone, tone.title())


_CAMP_FOCUS_LABELS = {
    "striking":     "Striking",
    "grappling":    "Grappling",
    "wrestling":    "Wrestling",
    "conditioning": "Conditioning",
    "submission":   "Submission",
    "clinch":       "Clinch",
    "general":      "General",
    "weight_cut":   "Weight Cut",
}


def _camp_focus_label(focus):
    """Return a Title Case label for a camp's focus."""
    if not focus:
        return "General"
    return _CAMP_FOCUS_LABELS.get(focus, focus.title())


# Phase M3.2 — promo size_tier → voice phrase (no raw tier strings in
# the UI per CONVENTIONS §14). Used by get_bidding_alerts to describe
# the rival promo's archetype in business-page register.
_SIZE_TIER_PHRASES = {
    "major": "Major-League Powerhouse",
    "mid":   "Mid-Tier Regional",
    "small": "Grassroots Operator",
}


def _size_tier_phrase(size_tier):
    return _SIZE_TIER_PHRASES.get(
        (size_tier or "").lower(), "Independent Promotion"
    )


def _compute_age(date_of_birth, sim_date):
    """Compute age in years from date_of_birth + sim_date."""
    if not date_of_birth or not sim_date:
        return 0
    try:
        dob = datetime.strptime(date_of_birth, "%Y-%m-%d")
        sim = datetime.strptime(sim_date, "%Y-%m-%d")
        age = sim.year - dob.year
        if (sim.month, sim.day) < (dob.month, dob.day):
            age -= 1
        return max(0, age)
    except Exception:
        return 0


# Ceiling phrase mapping (per SCREEN_DATA_AUDIT §3.7 + GUI_PLAN §6.4)
# NEVER returns the raw potential int — only the voice phrase.
_CEILING_PHRASES = [
    (90, 100, "Elite"),
    (80, 89,  "High"),
    (70, 79,  "Above-Avg"),
    (60, 69,  "Avg"),
    (50, 59,  "Below-Avg"),
    (0,  49,  "Low"),
]


def _ceiling_phrase_from_potential(potential):
    """Map a potential int (0-100) to a voice phrase."""
    if potential is None:
        return "Unknown"
    p = int(potential)
    for lo, hi, phrase in _CEILING_PHRASES:
        if lo <= p <= hi:
            return phrase
    return "Unknown"


def _ceiling_potential_ranges(ceiling_filter):
    """Return (low, high) potential range for a ceiling filter label.

    Used by get_free_agents() to filter FAs by ceiling tier.
    """
    mapping = {
        "elite":      (90, 100),
        "high":       (80, 89),
        "above_avg":  (70, 79),
        "above-avg":  (70, 79),
        "avg":        (60, 69),
        "below_avg":  (50, 59),
        "below-avg":  (50, 59),
        "low":        (0, 49),
    }
    rng = mapping.get((ceiling_filter or "").lower())
    return list(rng) if rng else None


def _result_type_label(result_type):
    """Map fight_history.result_type to a short label for display."""
    if not result_type:
        return ""
    m = {
        "unanimous_decision": "UD",
        "split_decision": "SD",
        "majority_decision": "MD",
        "decision": "DEC",
        "ko_tko": "KO/TKO",
        "submission": "SUB",
        "tko_stoppage": "TKO",
        "ko": "KO",
        "doctor_stoppage": "DR. STOP",
        "dq": "DQ",
        "draw": "DRAW",
        "no_contest": "NC",
        "nc": "NC",
    }
    return m.get(result_type.lower(), result_type.upper()[:8])


def _result_method_voice_phrase(result_type, finish_round=None,
                                finish_time=None):
    """P3.6 — voice-phrased result method for the recap screen.

    The existing _result_type_label returns terse sports-page labels
    ("KO/TKO", "SUB"). The recap screen wants more visceral language
    per the user's "where's the player reward?" complaint: "by
    devastating knockout" not "by KO/TKO", "by rear-naked choke" not
    "by submission". Voice-compliant per CONVENTIONS §14 (no raw
    numbers; "devastating" / "thunderous" / "crisp" are word-form
    descriptors, not stats).

    Args:
        result_type: the fight's result_type string.
        finish_round: int (1-5) — used for the round word.
        finish_time: "M:SS" string — used for the time phrase.

    Returns:
        A voice phrase like "by devastating knockout in the first round"
        or "by unanimous decision". Empty string for unknown types.
    """
    if not result_type:
        return ""
    rt = result_type.lower()
    # Round word for finish rounds.
    round_words = {1: "first", 2: "second", 3: "third", 4: "fourth",
                   5: "fifth"}
    rw = round_words.get(finish_round or 0, "")
    round_clause = f" in the {rw} round" if rw else ""
    # Time clause (voice-phrased, no raw "2:34").
    time_clause = ""
    if finish_time and finish_time not in ("0:00", "5:00"):
        try:
            parts = finish_time.split(":")
            if len(parts) == 2:
                total = int(parts[0]) * 60 + int(parts[1])
                if total < 60:
                    time_clause = " in the opening minute"
                elif total < 120:
                    time_clause = " past the midway mark"
                elif total < 180:
                    time_clause = " late in the round"
                elif total < 240:
                    time_clause = " as the round wound down"
                else:
                    time_clause = " deep into the round"
        except (ValueError, TypeError):
            pass

    phrases = {
        "ko_tko": "by devastating knockout",
        "ko": "by devastating knockout",
        "tko_stoppage": "by thunderous TKO",
        "submission": "by submission",
        "doctor_stoppage": "by doctor stoppage",
        "corner_stoppage": "by corner stoppage",
        "dq": "by disqualification",
        "unanimous_decision": "by unanimous decision",
        "split_decision": "by split decision",
        "majority_decision": "by majority decision",
        "decision": "by decision",
        "draw": "via draw",
        "no_contest": "via no contest",
        "nc": "via no contest",
    }
    base = phrases.get(rt)
    if not base:
        return ""
    # Finishes get the round + time clause; decisions don't.
    if rt in ("ko_tko", "ko", "tko_stoppage", "submission", "dq"):
        return base + round_clause + time_clause
    return base


# ----------------------------------------------------------------
# Fight Night voice-phrase helpers (Task FIGHT-NIGHT-SHOWCASE).
#
# Per CONVENTIONS §14: NO raw rating ints in the player-facing UI.
# These helpers convert the raw 0-100 performance_rating /
# fan_reaction_rating / show_rating axis values into voice phrases.
# ----------------------------------------------------------------

def _rating_voice_phrase(rating, kind="performance"):
    """Convert a 0-100 rating int to a voice phrase (no raw digits).

    Args:
        rating: 0-100 int (or None).
        kind: 'performance' (fight perf rating), 'fan' (fan reaction
            rating), or 'show' (show_rating axis). The kind selects
            the appropriate voice register — performance is in-ring
            quality, fan is crowd heat, show is overall event
            quality.

    Returns:
        Voice phrase string (no raw digits per §14).
    """
    if rating is None:
        return "no read yet"
    try:
        r = int(rating)
    except (ValueError, TypeError):
        return "no read yet"
    if kind == "performance":
        if r >= 90:
            return "an unforgettable performance"
        if r >= 80:
            return "a statement performance"
        if r >= 70:
            return "a strong showing"
        if r >= 60:
            return "a workmanlike effort"
        if r >= 50:
            return "a forgettable outing"
        return "a flat performance"
    if kind == "fan":
        if r >= 90:
            return "the crowd is on its feet"
        if r >= 80:
            return "the arena is electric"
        if r >= 70:
            return "the crowd is into it"
        if r >= 60:
            return "a respectful reception"
        if r >= 50:
            return "a polite reaction"
        return "the crowd is restless"
    if kind == "show":
        if r >= 90:
            return "an instant classic that fans will talk about for years"
        if r >= 75:
            return "a highly entertaining show that delivered on expectations"
        if r >= 60:
            return "a solid night of fights with some memorable moments"
        if r >= 40:
            return "a decent show that failed to produce many highlights"
        return "a lackluster card that left fans wanting more"
    return "no read yet"


def _severity_phrase_for_injury(severity):
    """Convert a 1-10 injury severity int to a voice phrase.

    Mirrors the inline helper in services/fight_engine.py — kept local
    to app_web.py to avoid the circular import (news.py imports
    voice.py, app_web.py imports news.py).
    """
    if severity is None:
        return "nagging"
    try:
        s = int(severity)
    except (ValueError, TypeError):
        return "nagging"
    if s <= 3:
        return "minor"
    if s <= 6:
        return "moderate"
    if s <= 8:
        return "serious"
    return "severe"


def _scout_confidence_phrase(confidence):
    """Map a 0-100 scout_confidence int to a voice phrase.

    Bands (per docs/P1_PLAN_WIRE_SCREENS.md §3 — P1-WIRE-4-SCREENS
    alignment with the spec's voice phrasing):
      80-100 → "highly confident"
      60-79  → "moderately confident"
      30-59  → "uncertain"
      0-29   → "wild guess"
    """
    if confidence is None:
        return "uncertain"
    try:
        c = int(confidence)
    except (TypeError, ValueError):
        return "uncertain"
    if c >= 80:
        return "highly confident"
    if c >= 60:
        return "moderately confident"
    if c >= 30:
        return "uncertain"
    return "wild guess"


def _is_expiring_soon(end_date, sim_date, days=90):
    """Return True if end_date is within `days` of sim_date."""
    if not end_date or not sim_date:
        return False
    try:
        ed = datetime.strptime(end_date, "%Y-%m-%d")
        sim = datetime.strptime(sim_date, "%Y-%m-%d")
        delta = (ed - sim).days
        return 0 <= delta <= days
    except Exception:
        return False


# ============================================================
# CR-2 (docs/CR1_4_PLAN.md §2): Attribute trajectory helper.
#
# Computes a per-attribute trajectory chip payload for the Fighter
# Profile Attributes tab. Each of the 26 fighter_attributes gets a
# small badge showing whether it is currently surging / growing /
# stable / declining / decaying — color-graded green → red.
#
# Inputs:
#   - training_camps.attribute_changes (JSON deltas from last 90 sim days)
#   - effective_ceiling = potential × age_factor × health_factor
#     (same formula as tick_processor.py post-CR-10; see G.1 fix —
#     personality_factor was REMOVED from the ceiling and moved into
#     the gain multiplier in tick_processor.py. This helper only needs
#     the ceiling for the "decaying" state check, so personality is
#     no longer factored here either.)
#
# Output (per attribute):
#   { "state": "growing", "delta_90d": 3, "reason": "..." }
#
# Constraints (per task spec §"Constraints"):
#   - NEVER expose the raw potential or effective_ceiling integer.
#     The "reason" string mentions qualitative state ("ceiling has
#     dropped below current level (age 34)") but NOT "ceiling=68,
#     current=72".
#   - Performance: <50ms per fighter. Uses 2 indexed-ish queries
#     (training_camps table is small — ~700 rows as of v3.16.0 —
#     so the scan is sub-millisecond).
# ============================================================

# The 26 fighter_attribute columns (per schema dump). Names mirror
# the columns in the fighter_attributes table verbatim — these are
# also the keys used in training_camps.attribute_changes JSON.
_FIGHTER_ATTR_COLUMNS = [
    "punch_power", "cardio", "fight_iq", "chin", "punch_accuracy",
    "kick_power", "kick_accuracy", "head_movement", "footwork",
    "clinch_striking", "clinch_offense", "clinch_defense",
    "takedown_offense", "takedown_defense", "top_control", "bottom_game",
    "submission_offense", "submission_defense", "scramble_ability",
    "cage_wrestling", "recovery_rate", "speed_explosiveness",
    "strength", "durability", "flexibility", "adaptability",
]


# Phase 6 / Task B1 — voice-phrase → tier pct mapping.
# Mirrors the phraseTier() helper in src/web/js/fighter_profile.js:75-101
# (Phase 5 Task 2.5) so the radar chart polygon coordinates derive from
# voice tiers rather than raw 0-100 attribute ints. This keeps the
# "how strong is this fighter?" answer in voice territory (§14) while
# still letting the polygon shapes convey relative magnitudes.
_PHRASE_TIER_GOLD = 100   # elite / world-class / exceptional / lethal / ...
_PHRASE_TIER_STEEL = 60   # default (no elite/weak keyword matched)
_PHRASE_TIER_CRIMSON = 25  # poor / weak / fragile / limited / ...
_PHRASE_ELITE_WORDS = (
    "elite", "world-class", "exceptional", "lethal", "master",
    "devastating", "top-tier", "elite-level", "powerful",
    "explosive", "iron", "titanium", "granite",
    "excellent", "dominant", "unstoppable",
)
_PHRASE_WEAK_WORDS = (
    "poor", "weak", "fragile", "limited", "vulnerable",
    "soft", "can be rocked", "questionable", "shaky",
    "below-average", "lacking", "lacks", "helpless",
)


def _phrase_tier_pct(phrase):
    """Map a voice phrase to a tier pct for radar-chart polygon points.

    Mirrors phraseTier() in src/web/js/fighter_profile.js:75-101.
    Returns 100 (gold), 25 (crimson), or 60 (steel default).

    Per Phase 6 / Task B1: the radar chart in matchmaking.js previously
    averaged raw 0-100 attribute ints (a §14 violation). The polygon
    now uses tier pct values so the player sees "elite vs elite" /
    "weak vs elite" relative magnitudes, not raw attribute numbers.
    """
    if not phrase:
        return _PHRASE_TIER_STEEL
    p = str(phrase).lower()
    for word in _PHRASE_ELITE_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", p):
            return _PHRASE_TIER_GOLD
    for word in _PHRASE_WEAK_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", p):
            return _PHRASE_TIER_CRIMSON
    return _PHRASE_TIER_STEEL


def _attribute_phrase_dicts(conn, fighter_id):
    """Return (phrases_dict, tiers_dict) for a fighter's 26 attributes.

    phrases_dict: {attr_name: voice_phrase}
    tiers_dict: {attr_name: tier_pct (100/60/25)}

    Reads from fighter_descriptors.attribute_descriptors JSON
    (Phase 6 / Task B1). Falls back to ('', 60) per attribute when
    the JSON is missing or the fighter row doesn't exist.
    """
    if not fighter_id:
        return ({}, {})
    row = conn.execute(
        "SELECT attribute_descriptors FROM fighter_descriptors "
        "WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    raw = row[0] if row else None
    try:
        parsed = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        parsed = {}
    phrases = {}
    tiers = {}
    for col in _FIGHTER_ATTR_COLUMNS:
        ph = parsed.get(col, "") or ""
        phrases[col] = ph
        tiers[col] = _phrase_tier_pct(ph)
    return (phrases, tiers)


def _compute_attribute_trajectory(conn, fighter_id, sim_date=None):
    """Return a dict of per-attribute trajectory metadata.

    See docs/CR1_4_PLAN.md §2.3 for the state table. Each attribute
    gets one of: surging / growing / stable / declining / decaying.

    Returns {} on hard failure (caller treats missing key as "no chip").
    """
    try:
        fid = int(fighter_id)
        if not sim_date:
            c = get_clock(conn)
            sim_date = c[0] if c else None
        if not sim_date:
            return {}

        # ----- Compute 90-day cutoff in sim time -----
        try:
            sim_dt = datetime.strptime(sim_date[:10], "%Y-%m-%d")
            cutoff_dt = sim_dt - timedelta(days=90)
            cutoff = cutoff_dt.strftime("%Y-%m-%d")
        except Exception:
            return {}

        # ----- Load fighter meta (dob, career_health, potential, -
        # discipline, coachability, all 26 attribute values) in one -
        # joined query. Falls back gracefully if any row is missing. -----
        meta_row = conn.execute(
            "SELECT f.date_of_birth, fc.career_health, fc.potential, "
            "fp.discipline, fp.coachability, "
            "fa.punch_power, fa.cardio, fa.fight_iq, fa.chin, fa.punch_accuracy, "
            "fa.kick_power, fa.kick_accuracy, fa.head_movement, fa.footwork, "
            "fa.clinch_striking, fa.clinch_offense, fa.clinch_defense, "
            "fa.takedown_offense, fa.takedown_defense, fa.top_control, fa.bottom_game, "
            "fa.submission_offense, fa.submission_defense, fa.scramble_ability, "
            "fa.cage_wrestling, fa.recovery_rate, fa.speed_explosiveness, "
            "fa.strength, fa.durability, fa.flexibility, fa.adaptability "
            "FROM fighters f "
            "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
            "LEFT JOIN fighter_personality fp ON fp.fighter_id = f.fighter_id "
            "LEFT JOIN fighter_attributes fa ON fa.fighter_id = f.fighter_id "
            "WHERE f.fighter_id = ?",
            (fid,),
        ).fetchone()
        if not meta_row:
            return {}

        dob_str = meta_row[0]
        career_health = meta_row[1] if meta_row[1] is not None else 100
        potential = meta_row[2] if meta_row[2] is not None else 50
        # CR-10 fix: discipline + coachability are loaded but no longer
        # factor into effective_ceiling (personality was moved into the
        # gain multiplier in tick_processor.py; this trajectory helper
        # only needs the ceiling for the "decaying" state check). Kept
        # in the SELECT for defensive context — a future "low-discipline
        # slows growth" chip reason could use these.
        discipline = meta_row[3] if meta_row[3] is not None else 50  # noqa: F841
        coachability = meta_row[4] if meta_row[4] is not None else 50  # noqa: F841
        # attribute values start at index 5 (26 cols)
        current_vals = {col: (meta_row[5 + i] if meta_row[5 + i] is not None else 50)
                        for i, col in enumerate(_FIGHTER_ATTR_COLUMNS)}

        # ----- Compute age (sim time, not wall-clock) -----
        age = _compute_age(dob_str, sim_date) if dob_str else 25

        # ----- effective_ceiling (mirrors tick_processor.py:646-674) -----
        # CR-10 fix (docs/CR10_14_FIX_PLAN.md §1): personality_factor
        # removed from ceiling calc — same change as tick_processor.py
        # G.1. The ceiling is bounded only by age + health; personality
        # affects gain rate, not ceiling. The trajectory chip reads
        # effective_ceiling to decide if attributes are "decaying"
        # (ceiling dropped below current). With the old formula, every
        # fighter's ceiling was artificially low → every fighter showed
        # "decaying" even at age 25. With the fix, only age+health-
        # bounded fighters show decay.
        if age <= 27:
            age_factor = 1.0
        elif age <= 30:
            age_factor = 0.95
        elif age <= 33:
            age_factor = 0.80
        elif age <= 36:
            age_factor = 0.60
        else:
            age_factor = 0.35

        if career_health >= 90:
            health_factor = 1.0
        elif career_health >= 70:
            health_factor = 0.90
        elif career_health >= 50:
            health_factor = 0.70
        elif career_health >= 30:
            health_factor = 0.40
        else:
            health_factor = 0.15

        effective_ceiling = max(10, int(potential * age_factor *
                                        health_factor))

        # ----- Sum training_camps.attribute_changes deltas for last 90d -
        per_attr_delta = {col: 0 for col in _FIGHTER_ATTR_COLUMNS}
        camp_count = 0
        camp_rows = conn.execute(
            "SELECT attribute_changes FROM training_camps "
            "WHERE fighter_id = ? AND is_completed = 1 "
            "  AND end_date >= ? AND end_date <= ? "
            "  AND attribute_changes IS NOT NULL",
            (fid, cutoff, sim_date[:10]),
        ).fetchall()
        for (changes_json,) in camp_rows:
            if not changes_json:
                continue
            try:
                changes = json.loads(changes_json)
            except Exception:
                continue
            if not isinstance(changes, dict):
                continue
            camp_count += 1
            for attr_name, delta in changes.items():
                if attr_name in per_attr_delta and isinstance(delta, (int, float)):
                    per_attr_delta[attr_name] += int(delta)

        # ----- Build per-attribute trajectory dict -----
        trajectory = {}
        for col in _FIGHTER_ATTR_COLUMNS:
            delta_90d = per_attr_delta[col]
            current = current_vals[col]

            # Precedence (per docs/CR1_4_PLAN.md §2.3 + task spec):
            # 1. Recent growth (surging/growing) wins — the chip is
            #    primarily a "what's happening right now" signal.
            # 2. If no recent growth AND age ≥ 33 AND ceiling dropped →
            #    decaying (red, terminal).
            # 3. If no recent growth AND (ceiling dropped OR net loss) →
            #    declining (orange).
            # 4. Otherwise → stable (gray).
            if delta_90d >= 5:
                state = "surging"
                reason = (f"Surging — gained +{delta_90d} from "
                          f"{camp_count} training camp"
                          f"{'s' if camp_count != 1 else ''} in last 90 days")
            elif 1 <= delta_90d <= 4:
                state = "growing"
                reason = (f"Growing — gained +{delta_90d} from "
                          f"{camp_count} training camp"
                          f"{'s' if camp_count != 1 else ''} in last 90 days")
            elif effective_ceiling < current and age >= 33:
                state = "decaying"
                reason = (f"Decaying — age-related decline (age {age}); "
                          f"ceiling has dropped below current level")
            elif effective_ceiling < current or delta_90d <= -1:
                state = "declining"
                if delta_90d <= -1:
                    reason = (f"Declining — lost {delta_90d} in last "
                              f"90 days")
                else:
                    reason = ("Declining — ceiling has dropped below "
                              "current level")
            else:
                state = "stable"
                if camp_count == 0:
                    reason = "Stable — no recent training camps"
                else:
                    reason = (f"Stable — no net change in last 90 days "
                              f"across {camp_count} camp"
                              f"{'s' if camp_count != 1 else ''}")

            trajectory[col] = {
                "state": state,
                "delta_90d": delta_90d,
                "reason": reason,
            }
        return trajectory
    except Exception as e:
        print(f"[app_web._compute_attribute_trajectory] {e}", flush=True)
        return {}


def _load_logo_b64(promo_id):
    """Load a promotion's logo as a base64 string for inline <img> use."""
    try:
        for f in LOGO_DIR.glob("*.png"):
            if f.name.startswith(f"{promo_id}_"):
                with open(f, "rb") as fh:
                    return base64.b64encode(fh.read()).decode()
    except Exception:
        pass
    return ""


# ============================================================
# PHASE M4 — Matchmaking Heartbeat helpers
#
# Per docs/MASTER_PLAN_MATCHMAKING.md §1.3 + §1.4, the live preview
# must use the REAL card_draw_multiplier formula from finance.py
# (lines 384-390), not the hardcoded `card_draw = 1.2` that
# `get_event_preview` shipped with. These helpers compute the real
# card_draw from the actual booked fights on the card + provide
# per-fight matchup-quality scoring (mirror of
# services.rival_ai.matchmaker._matchup_score) + voice-layer
# card-health warnings.
#
# All helpers are read-only — no DB writes. The Api methods that
# follow (book_fight / remove_fight / reorder_fights) perform the
# writes and then call these helpers to return the updated preview.
# ============================================================

# Voice phrases for the projected card draw (0-100 scale).
# Mirrors show_rating.py's vocabulary ("instant classic" / "highly
# entertaining" / "solid night" / "decent show" / "lackluster") per
# docs/RESEARCH_MATCHMAKING_SHOWRATING.md §"show_rating voice vocab".
def _card_draw_voice_phrase(card_draw_score):
    """Convert a 0-100 card_draw score to a voice phrase.

    Per docs/MASTER_PLAN_MATCHMAKING.md §1.2: "This card will pack
    the arena" / "A solid night of fights" / "Fans will demand
    refunds" / "This card has no pulse".
    """
    if card_draw_score >= 85:
        return "This card will pack the arena."
    if card_draw_score >= 70:
        return "A strong night of fights — fans will get their money's worth."
    if card_draw_score >= 55:
        return "A solid night of fights."
    if card_draw_score >= 40:
        return "A decent card — the faithful will tune in."
    if card_draw_score >= 25:
        return "Fans will demand refunds."
    return "This card has no pulse."


def _matchup_quality_phrase(score):
    """Convert a 0-100 matchup_score to a voice phrase for the chip.

    Per docs/MASTER_PLAN_MATCHMAKING.md §1.2: "elite matchup" /
    "solid fight" / "tune-up" / "mismatch". The chip also shows
    the score as a 2-digit number (allowed — it's the pundit's
    quality verdict, NOT a hidden attribute).
    """
    if score >= 80:
        return ("elite", "gold")
    if score >= 65:
        return ("strong matchup", "gold")
    if score >= 50:
        return ("solid fight", "green")
    if score >= 35:
        return ("tune-up", "default")
    if score >= 20:
        return ("soft matchup", "warning")
    return ("mismatch", "crimson")


# ============================================================
# PHASE MM1 — Matchmaking V2 helpers
#
# Per docs/MASTER_PLAN_MATCHMAKING_V2.md (MM1.2 + MM1.3 + MM1.6),
# the matchmaking screen surfaces 9 fighter-info fields in each
# corner slot + a "might"-framed analysis (no definitive predictions,
# no raw numeric scores). These helpers compute the voice-layer
# phrases for popularity tier, momentum label, recent form, title
# chip, rivalry chip, and the "might"-style analysis phrases.
#
# All helpers are read-only. The Api methods below call them.
# ============================================================

def _popularity_tier(marketability):
    """Convert a 0-100 marketability score to a voice phrase label.

    Delegates to the canonical ``interpretation.marketability.
    marketability_tier`` (Tier 2 / W38 — one authoritative calculation
    per meaning). The 4-tier label set is preserved verbatim — the JS
    in ``src/web/js/matchmaking.js`` checks ``tier === 'Cult Hero'``
    for the gold-chip CSS class.

    Per docs/MASTER_PLAN_MATCHMAKING_V2.md §MM1.2 #5 (mirrors WMMA5's
    "Name Value" tiers). Voice-layer: NO raw numbers — just the tier
    label the player reads like a marketing band.
    """
    # Lazy import — keeps app_web importable in headless test setups.
    try:
        from interpretation.marketability import marketability_tier
        return marketability_tier(marketability)
    except ImportError:
        # Fallback — original implementation (verbatim).
        if marketability is None:
            return "Unknown"
        m = int(marketability)
        if m >= 80:
            return "Cult Hero"
        if m >= 60:
            return "Rising Star"
        if m >= 40:
            return "Mid Level"
        return "Unknown"


def _momentum_label(win_streak, loss_streak):
    """Build a momentum indicator dict (arrow + label + streak str).

    Returns:
        {
            "arrow": "▲"|"▼"|"→",
            "color": "hot"|"cold"|"flat",
            "label": "Hot Streak"|"Cold Streak"|"Stable",
            "streak_str": "3W"|"2L"|"" (empty when neither streak >= 2),
        }

    Per MM1.2 #6: ▲ green (hot) / ▼ red (cold) / → gray (stable) +
    the streak number so the player can scan recent form at a glance.
    """
    ws = int(win_streak or 0)
    ls = int(loss_streak or 0)
    if ws >= 2:
        return {
            "arrow": "▲",
            "color": "hot",
            "label": "Hot Streak",
            "streak_str": f"{ws}W",
        }
    if ls >= 2:
        return {
            "arrow": "▼",
            "color": "cold",
            "label": "Cold Streak",
            "streak_str": f"{ls}L",
        }
    return {
        "arrow": "→",
        "color": "flat",
        "label": "Stable",
        "streak_str": "",
    }


def _recent_form(conn, fighter_id, limit=5):
    """Return the fighter's last N fights as W/L/D blocks.

    Each block: {"letter": "W"|"L"|"D"|"N", "outcome": "win"|...,
                  "result_type": str, "finish_round": int,
                  "event_date": str}

    Ordered oldest → newest (so the rightmost chip is the most recent
    fight, matching WMMA5's convention).
    """
    if not fighter_id:
        return []
    rows = conn.execute(
        "SELECT outcome, result_type, finish_round, event_date "
        "FROM fight_history "
        "WHERE fighter_id=? "
        "ORDER BY fight_history_id DESC LIMIT ?",
        (fighter_id, int(limit)),
    ).fetchall()
    blocks = []
    for (outcome, rtype, rnd, ev_date) in rows:
        letter = 'W' if outcome == 'win' else (
            'L' if outcome == 'loss' else (
                'D' if outcome == 'draw' else 'N'))
        blocks.append({
            "letter": letter,
            "outcome": outcome or "",
            "result_type": rtype or "",
            "finish_round": rnd,
            "event_date": ev_date or "",
        })
    # Reverse so oldest is leftmost (WMMA5 convention).
    blocks.reverse()
    return blocks


def _title_chip(conn, fighter_id):
    """Return the title-chip dict for a fighter.

    {"holds_title": bool, "title_label": str,
     "weight_class_name": str|None, "weight_class_id": int|None}

    The title_label is voice-friendly: "LW Champion" or "—".
    A fighter can hold multiple titles (theoretically — one per WC);
    we surface the first non-vacant one. If the fighter holds no
    title, holds_title is False + title_label is "—".
    """
    if not fighter_id:
        return {"holds_title": False, "title_label": "—",
                "weight_class_name": None, "weight_class_id": None}
    row = conn.execute(
        "SELECT t.title_id, t.weight_class_id, wc.name "
        "FROM titles t "
        "JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id "
        "WHERE t.current_champion_fighter_id=? AND t.is_vacant=0 "
        "ORDER BY t.title_id ASC LIMIT 1",
        (fighter_id,),
    ).fetchone()
    if not row:
        return {"holds_title": False, "title_label": "—",
                "weight_class_name": None, "weight_class_id": None}
    (_tid, wc_id, wc_name) = row
    # Shorten "Lightweight" → "LW", "Welterweight" → "WW", etc.
    short = _short_wc(wc_name)
    return {
        "holds_title": True,
        "title_label": f"{short} Champion",
        "weight_class_name": wc_name,
        "weight_class_id": wc_id,
    }


def _short_wc(wc_name):
    """Shorten a weight class name for compact chip display."""
    if not wc_name:
        return "—"
    n = wc_name.strip()
    mapping = {
        "Heavyweight": "HW",
        "Light Heavyweight": "LHW",
        "Middleweight": "MW",
        "Welterweight": "WW",
        "Lightweight": "LW",
        "Featherweight": "FW",
        "Bantamweight": "BW",
        "Flyweight": "FlyW",
        "Strawweight": "SW",
        "Atomweight": "AW",
        "Super Heavyweight": "SHW",
        "Catchweight": "CW",
    }
    return mapping.get(n, n)


def _rivalry_heat(conn, fighter_a_id, fighter_b_id):
    """Check whether two fighters have an active rivalry.

    Returns: {"has_rivalry": bool, "heat": int 0-100,
              "type": str, "label": str}

    Per MM1.2 #8: heat >= 50 -> show RIVALRY chip on the VS strip.
    The label is the rivalry_type in human form ("Title Rivalry",
    "Rematch Hungry", "Bitter Blood").
    """
    if not fighter_a_id or not fighter_b_id:
        return {"has_rivalry": False, "heat": 0, "type": "", "label": ""}
    a, b = fighter_a_id, fighter_b_id
    # Rivalry rows may be stored either direction.
    row = conn.execute(
        "SELECT rivalry_heat, rivalry_type, fights_count, "
        "fighter_a_wins, fighter_b_wins, draws "
        "FROM rivalries "
        "WHERE is_active=1 AND "
        "((fighter_a_id=? AND fighter_b_id=?) OR "
        " (fighter_a_id=? AND fighter_b_id=?)) "
        "ORDER BY rivalry_heat DESC LIMIT 1",
        (a, b, b, a),
    ).fetchone()
    if not row:
        return {"has_rivalry": False, "heat": 0, "type": "", "label": ""}
    heat, rtype, n_fights, a_wins, b_wins, draws = row
    heat = int(heat or 0)
    if heat < 50:
        return {"has_rivalry": False, "heat": heat, "type": rtype or "",
                "label": ""}
    label = _rivalry_type_label(rtype, heat, n_fights or 0,
                                 a_wins or 0, b_wins or 0, draws or 0)
    return {
        "has_rivalry": True,
        "heat": heat,
        "type": rtype or "",
        "label": label,
    }


def _rivalry_type_label(rtype, heat, n_fights, a_wins, b_wins, draws):
    """Build a voice-friendly rivalry label.

    Examples: "Bitter Blood · 1-1" / "Title Rivalry · 0-0" /
    "Rematch Hungry · heat 97".
    """
    if not rtype:
        return f"Rivalry · {a_wins}-{b_wins}"
    rtype_norm = rtype.replace("_", " ").title()
    if n_fights and (a_wins or b_wins or draws):
        return f"{rtype_norm} · {a_wins}-{b_wins}" + (
            f"-{draws}" if draws else "")
    return f"{rtype_norm} · heat {heat}"


def _surface_memories_safe(conn, fighter_a_id, fighter_b_id):
    """HW3.5 (docs/Hardening_Phase.md §HW3.5) — surface relevant
    memories for a fighter pair, defensively.

    Wraps memory_engine.surface_memories in a try/except so a memory-
    lookup failure (missing table, transient error, edge-case data)
    can NEVER crash the matchmaking / book_fight flow. Returns a list
    of {"type": str, "phrase": str} dicts (transformed from the
    engine's (type, phrase) tuples so the JS side can JSON-serialize
    them directly).

    Per memory_engine D3: the engine is READ-ONLY. Per D6: the engine
    never raises — but we add our own try/except here as belt-and-
    suspenders (the engine's own error handling is per-search-type;
    a top-level error like a missing imports would still propagate).

    Args:
        conn: sqlite3.Connection.
        fighter_a_id, fighter_b_id: ints (red + blue corner fighters).

    Returns:
        list of dicts: [{"type": "previous_fight",
                         "phrase": "Last met three years ago."}, ...]
        Empty list on any error or if no memories match.
    """
    if not fighter_a_id or not fighter_b_id:
        return []
    if fighter_a_id == fighter_b_id:
        return []
    try:
        from interpretation.memory_engine import surface_memories
        pairs = surface_memories(conn, fighter_a_id, fighter_b_id)
        # pairs is a list of (memory_type, phrase) tuples — transform
        # to dicts for JSON serialization (tuples become lists in
        # JSON, which loses the type/phrase distinction).
        return [{"type": t, "phrase": p} for t, p in pairs]
    except Exception as e:
        print(f"[_surface_memories_safe] a={fighter_a_id} "
              f"b={fighter_b_id}: {e}", flush=True)
        return []


# P1-WIRE-4-SCREENS — voice helpers for the Bad Blood screen.
# Per docs/P1_PLAN_WIRE_SCREENS.md §1 + CONVENTIONS §14:
#   - heat is OK to display as a raw 0-100 integer (relationship
#     rating, not a fighter attribute)
#   - heat_phrase is the voice-layer wrapper ("simmering" /
#     "heating up" / "boiling over" / "ready to explode")
_RIVALRY_TYPE_PRETTY = {
    "callout":            "Callout",
    "bad_blood":          "Bad Blood",
    "title_rivalry":      "Title Rivalry",
    "rematch_hungry":     "Rematch Hungry",
    "style_clash":        "Style Clash",
    "disrespect":         "Disrespect",
    "stolen_opportunity": "Stolen Opportunity",
}


def _rivalry_type_pretty(rtype):
    """Return a player-friendly rivalry_type label (Title Case)."""
    if not rtype:
        return ""
    return _RIVALRY_TYPE_PRETTY.get(rtype, rtype.replace("_", " ").title())


def _rivalry_heat_phrase(heat):
    """Return a voice phrase for a rivalry heat value (0-100).

    Bands (per docs/P1_PLAN_WIRE_SCREENS.md §1):
      0-19   → "cold"          (dormant — below the dormancy threshold)
      20-39  → "simmering"
      40-59  → "heating up"
      60-79  → "boiling over"
      80-100 → "ready to explode"
    """
    try:
        h = int(heat)
    except (TypeError, ValueError):
        h = 0
    if h >= 80:
        return "ready to explode"
    if h >= 60:
        return "boiling over"
    if h >= 40:
        return "heating up"
    if h >= 20:
        return "simmering"
    return "cold"


def _rivalry_fighter_stage(conn, fighter_id):
    """Return a voice-layer career-stage phrase for a rivalry fighter.

    Uses the existing voice.describe_career_stage helper (already
    imported by rivalries.py). Returns "" if the fighter is missing
    or the voice layer is unavailable.
    """
    if not fighter_id:
        return ""
    try:
        from rivalries import _fighter_career_stage
        return _fighter_career_stage(conn, fighter_id) or ""
    except Exception:
        return ""


# "Might"-advice phrases for the analysis (replaces definitive
# predictions per MM1.3 — NO "Predicted Winner", NO confidence
# word, NO upset risk, NO raw matchup_score in the chip).
_MIGHT_STYLE_PHRASES = {
    "striker_vs_grappler": [
        "This one might favor the striker if they can keep it standing — "
        "but the grappler has the tools to make it interesting on the mat.",
        "If the striker can defend the takedown, this could be a long "
        "night for the grappler. If not, the ground is a different fight.",
    ],
    "two_strikers": [
        "Two strikers, two chins tested — could end in a flash either way.",
        "Expect exchanges on the feet. The first clean shot might decide it.",
    ],
    "two_grapplers": [
        "Two grapplers with submission instincts — anticipate ground "
        "exchanges; could go long if neither secures the finish.",
        "A chess match on the mat is the early read — patience may win "
        "this one.",
    ],
    "wrestler_vs_any": [
        "The wrestler might grind this into a decision — but if the "
        "opponent has scrambling ability, the script can flip in a hurry.",
        "Pace and pressure are the wrestler's path. The opponent has to "
        "find a way to make them pay for entries.",
    ],
    "balanced": [
        "On paper, this might be closer than it looks — both fighters "
        "have the tools to impose their style.",
        "Could go either way — the early read says it comes down to who "
        "imposes their game plan first.",
    ],
}

_MIGHT_EARLY_READ = [
    "On paper, this might be a competitive fight — neither fighter has "
    "a clear runaway edge.",
    "The early read suggests a measured affair — both have paths to "
    "victory.",
    "If either fighter can impose their style early, the matchup could "
    "tilt quickly.",
    "The numbers don't separate these two by much — a coin flip on "
    "paper.",
    "Styles make fights, and these styles could produce something "
    "memorable — or a tactical stalemate.",
]

_MIGHT_EXCITEMENT_HIGH = [
    "This could be a classic — two fighters who come to win.",
    "Expect fireworks if both fight to their strengths.",
    "A fan-friendly fight on paper — pace and power on both sides.",
]

_MIGHT_EXCITEMENT_MID = [
    "A solid night of fighting is the early read — expect a measured pace.",
    "Should be a competitive affair — neither fighter runs away with it "
    "on paper.",
    "Could turn into a tactical battle if the early exchanges don't "
    "produce a finish.",
]

_MIGHT_EXCITEMENT_LOW = [
    "Tune-up vibes — one fighter's tools may outclass the other on paper.",
    "A patient, grinding affair is the early read.",
    "Don't expect fireworks — styles suggest a slow burn.",
]


def _style_matchup_phrase(style_a, style_b, rng=None):
    """Return a "might"-framed style matchup phrase (no predictions).

    Picks a phrase bucket based on the two fighters' style archetype
    names (e.g. "Striker" vs "Grappler"). Returns one of the
    `_MIGHT_STYLE_PHRASES` strings. Voice-compliant (CONVENTIONS §14):
    no raw numbers, no winner predictions, no confidence ratings.
    """
    import random as _r
    if rng is None:
        rng = _r
    styles = {style_a or "Balanced", style_b or "Balanced"}
    striker_types = {"Striker", "Brawler", "Counter-Striker"}
    grappler_types = {"Grappler", "Submission Specialist"}
    if styles & grappler_types and styles & striker_types:
        bucket = _MIGHT_STYLE_PHRASES["striker_vs_grappler"]
    elif styles <= striker_types:
        bucket = _MIGHT_STYLE_PHRASES["two_strikers"]
    elif styles <= grappler_types:
        bucket = _MIGHT_STYLE_PHRASES["two_grapplers"]
    elif "Wrestler" in styles:
        bucket = _MIGHT_STYLE_PHRASES["wrestler_vs_any"]
    else:
        bucket = _MIGHT_STYLE_PHRASES["balanced"]
    return rng.choice(bucket)


def _early_read_phrase(attribute_gap, rng=None):
    """Return a "might"-framed early-read phrase.

    The attribute_gap (0-100 ish, the unsigned difference between the
    two fighters' key-attribute averages) selects the bucket:
      - gap < 5 → close / coin-flip phrasing
      - gap 5-15 → competitive phrasing
      - gap >= 15 → measured / clear-on-paper phrasing

    Voice-compliant: NEVER says who the winner is.
    """
    import random as _r
    if rng is None:
        rng = _r
    gap = float(attribute_gap or 0)
    if gap < 5:
        return rng.choice([
            "On paper, this might be a coin flip — neither fighter "
            "separates from the other on the key attributes.",
            "The early read says it's close — a tactical round or two "
            "could decide it.",
            "Styles suggest this could go either way — the early "
            "exchanges will tell the story.",
        ])
    if gap < 15:
        return rng.choice([
            "On paper, this might be competitive — one fighter has a "
            "measurable edge, but the gap is small enough to flip.",
            "The early read suggests a measured affair — the favorite "
            "has the tools, but the underdog has the openings.",
            "Could tilt either way — the first fighter to impose their "
            "style likely takes it.",
        ])
    return rng.choice([
        "On paper, this might lean one way — but the underdog has the "
        "tools to make it interesting if the favorite gets complacent.",
        "The early read suggests a clear-on-paper edge — but a clear "
        "edge doesn't win fights on its own.",
        "Could be a dominant performance, or the underdog could make "
        "it interesting — depends on which version of each fighter "
        "shows up.",
    ])


def _excitement_phrase_might(excitement_score, rng=None):
    """Return a "might"-framed excitement phrase (no confidence rating).

    Buckets by 0-100 score: high (≥65), mid (45-64), low (<45). Voice-
    compliant: no numbers, no winner/method predictions.
    """
    import random as _r
    if rng is None:
        rng = _r
    s = int(excitement_score or 50)
    if s >= 65:
        return rng.choice(_MIGHT_EXCITEMENT_HIGH)
    if s >= 45:
        return rng.choice(_MIGHT_EXCITEMENT_MID)
    return rng.choice(_MIGHT_EXCITEMENT_LOW)


def _build_fighter_dict_for_matchup(conn, fighter_id):
    """Build a fighter dict with the fields matchmaker._matchup_score
    expects (rating, weight_class_id, gender, win_streak, loss_streak,
    potential, age, reputation).

    This is the per-fighter-data path used by the Matchmaking screen
    when a fight is ALREADY booked — the fighter is no longer in the
    `_get_available_fighters_for_card` list (they're not available for
    ANOTHER booking), but we still need their data to compute the
    matchup quality chip on the booked fight.

    Reuses the existing finance helper fields + the rankings table
    for the ELO rating. Returns None if the fighter doesn't exist.
    """
    if not fighter_id:
        return None
    row = conn.execute(
        "SELECT f.fighter_id, f.weight_class_id, f.gender, "
        "f.date_of_birth, f.marketability, "
        "COALESCE(fc.record_wins, 0), COALESCE(fc.record_losses, 0), "
        "COALESCE(fc.record_draws, 0), COALESCE(fc.win_streak, 0), "
        "COALESCE(fc.loss_streak, 0), COALESCE(fc.potential, 50), "
        "COALESCE(r.rating, 1000.0) "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id = f.fighter_id "
        "  AND r.weight_class_id = f.weight_class_id "
        "  AND r.promotion_id = f.current_promotion_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return None
    (fid, wc_id, gender, dob, mkt, w, l, d, ws, ls, pot, rating) = row
    # Compute age from DOB + sim clock (mirrors punditry._fighter_age).
    age = 30
    if dob:
        clock_row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        ref_str = clock_row[0] if clock_row else None
        if ref_str:
            try:
                dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                ref_dt = datetime.strptime(ref_str, "%Y-%m-%d")
                age = ref_dt.year - dob_dt.year
                if (ref_dt.month, ref_dt.day) < (dob_dt.month, dob_dt.day):
                    age -= 1
            except (ValueError, TypeError):
                pass
    return {
        'fighter_id': fid,
        'weight_class_id': wc_id,
        'gender': gender,
        'rating': rating,
        'record_wins': w,
        'record_losses': l,
        'record_draws': d,
        'win_streak': ws,
        'loss_streak': ls,
        'potential': pot,
        'age': age,
        'reputation': mkt or 50,  # marketability used as reputation proxy
        'marketability': mkt or 50,
    }


def _compute_matchup_score(conn, red_dict, blue_dict):
    """Compute the 0-100 matchup score for a fighter pair.

    Reuses services.rival_ai.matchmaker._matchup_score directly —
    weights are 35% marketability + 30% competitiveness + 20%
    storyline + 15% development_value per the existing arch doc §3.2.
    """
    try:
        from services.rival_ai.matchmaker import _matchup_score
        return float(_matchup_score(red_dict, blue_dict, conn=conn))
    except Exception as e:
        print(f"[_compute_matchup_score] {e}", flush=True)
        # Defensive fallback — marketability-only 0-100 average.
        try:
            r = (red_dict or {}).get('marketability', 50)
            b = (blue_dict or {}).get('marketability', 50)
            return float((r + b) / 2.0)
        except Exception:
            return 50.0


def _fighter_display_name(conn, fighter_id):
    """Return a fighter's display name (first + last) for use in error
    messages + news items. Falls back to 'Fighter {id}' on lookup
    failure (defensive — should never happen but won't crash the
    booking flow if it does).
    """
    if not fighter_id:
        return "Unknown fighter"
    row = conn.execute(
        "SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return f"Fighter {fighter_id}"
    fn, ln = row
    return f"{fn or ''} {ln or ''}".strip() or f"Fighter {fighter_id}"


def _short_notice_willingness(conn, fighter_id):
    """Compute a fighter's willingness (0-100) to accept a short-notice
    bout (event ≤ 14 days away).

    Per docs/MASTER_PLAN_MATCHMAKING_V2.md §3.3:
        willingness = 50  # base
        willingness += (risk_taking - 50) * 0.3      # risk-takers more willing
        willingness += (ambition - 50) * 0.2          # ambitious more willing
        willingness -= (professionalism - 50) * 0.3   # pros want a proper camp
        willingness -= (patience - 50) * 0.2          # patient less willing

    Returns the float willingness score. A score < 30 means the
    fighter REJECTS the short-notice bout (caller's responsibility to
    enforce).

    Defensive — if the personality columns are NULL/missing, returns
    50.0 (neutral, may accept or reject).

    The personality columns live in the `fighter_personality` table
    (not the `fighters` table itself), so we LEFT JOIN on fighter_id.
    A fighter with no personality row (e.g., a fresh seed) falls back
    to 50.0.
    """
    if not fighter_id:
        return 50.0
    row = conn.execute(
        "SELECT fp.risk_taking, fp.ambition, fp.professionalism, "
        "fp.patience "
        "FROM fighter_personality fp "
        "WHERE fp.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return 50.0
    risk_taking, ambition, professionalism, patience = row
    # Coalesce NULLs to 50 (the schema default for personality columns).
    risk_taking = risk_taking if risk_taking is not None else 50
    ambition = ambition if ambition is not None else 50
    professionalism = professionalism if professionalism is not None else 50
    patience = patience if patience is not None else 50
    willingness = 50.0
    willingness += (risk_taking - 50) * 0.3
    willingness += (ambition - 50) * 0.2
    willingness -= (professionalism - 50) * 0.3
    willingness -= (patience - 50) * 0.2
    return willingness


def _project_card_draw(conn, event_id, levers=None):
    """Compute the REAL card_draw_multiplier from the actual booked
    fights on the card.

    Per docs/MASTER_PLAN_MATCHMAKING.md §1.3: replaces the hardcoded
    `card_draw = 1.2` in `get_event_preview` with the real formula
    from `finance.py::_compute_broadcast_revenue` (lines 384-390):

        card_draw_multiplier = (
            1.0
            + 0.5 * (me_mkt / 100.0)
            + 0.2 * (co_mkt / 100.0)
            + 0.3 * (n_title / 2.0)
            + 0.1 * (n_rivalry / 3.0)
        )

    The helpers `_get_main_event_marketability` / `_get_co_main_
    marketability` / `_count_title_fights` / `_count_rivalry_fights_
    heat_50_plus` / `_get_avg_card_marketability` already exist in
    finance.py — this function calls them directly so we don't
    reinvent the formula.

    Args:
        conn: sqlite3.Connection.
        event_id: the event whose booked fights to score.
        levers: optional dict overriding the event row's levers
            (ticket_price, marketing_spend, ppv_price, is_ppv).

    Returns:
        {
            card_draw,              # float multiplier (1.0-2.5 ish)
            card_draw_score,        # int 0-100 (the voice-layer score)
            card_draw_phrase,       # voice phrase
            me_marketability,       # int 0-100 (main event)
            co_marketability,       # int 0-100 (co-main)
            n_title_fights,         # int
            n_rivalry_fights,       # int
            avg_card_marketability, # int 0-100
            n_fights,               # int (fights on the card)
            card_health_flags,      # list of warning strings
        }
    """
    from finance import (
        _get_main_event_marketability,
        _get_co_main_marketability,
        _count_title_fights,
        _count_rivalry_fights_heat_50_plus,
        _get_avg_card_marketability,
    )
    me_mkt = _get_main_event_marketability(conn, event_id)
    co_mkt = _get_co_main_marketability(conn, event_id)
    n_title = _count_title_fights(conn, event_id)
    n_rivalry = _count_rivalry_fights_heat_50_plus(conn, event_id)
    avg_mkt = _get_avg_card_marketability(conn, event_id)
    n_fights_row = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=?", (event_id,),
    ).fetchone()
    n_fights = int(n_fights_row[0] or 0) if n_fights_row else 0

    card_draw = (
        1.0
        + 0.5 * (me_mkt / 100.0)
        + 0.2 * (co_mkt / 100.0)
        + 0.3 * (n_title / 2.0)
        + 0.1 * (n_rivalry / 3.0)
    )

    # Card-draw SCORE on 0-100 scale for the voice-layer chip.
    # Computed from the same inputs the multiplier uses, normalized.
    # me_mkt is the heaviest weight (50%), co_mkt 20%, title 15%,
    # rivalry 10%, avg_mkt 5%. Capped 0-100.
    card_draw_score = int(round(
        0.50 * me_mkt +
        0.20 * co_mkt +
        0.15 * min(100, n_title * 50) +
        0.10 * min(100, n_rivalry * 33) +
        0.05 * avg_mkt
    ))
    card_draw_score = max(0, min(100, card_draw_score))
    card_draw_phrase = _card_draw_voice_phrase(card_draw_score)

    # Card-health checklist (per spec §"Card Health checklist").
    health_flags = _compute_card_health_flags(
        conn, event_id, n_fights, me_mkt, co_mkt, n_title,
    )

    return {
        "card_draw": round(card_draw, 3),
        "card_draw_score": card_draw_score,
        "card_draw_phrase": card_draw_phrase,
        "me_marketability": me_mkt,
        "co_marketability": co_mkt,
        "n_title_fights": n_title,
        "n_rivalry_fights": n_rivalry,
        "avg_card_marketability": avg_mkt,
        "n_fights": n_fights,
        "card_health_flags": health_flags,
    }


def _compute_card_health_flags(conn, event_id, n_fights,
                                me_mkt, co_mkt, n_title):
    """Compute the Card Health checklist warnings (per spec).

    Returns a list of {flag, severity, phrase} dicts. Each warning
    is shown as a row in the Live Projection panel.

    Flags:
      - "Main event weaker than co-main" (me_mkt < co_mkt)
      - "No title fight on a PPV" (is_ppv=1 and n_title=0)
      - "Card has 0 hometown fighters" (no fighter born in event city)
      - "Main event fighter on cold streak" (loss_streak >= 2)
      - "Style diversity: too many same-style fights" (4+ of same arch)
      - "Card is too thin" (n_fights < 4)
      - "Card is too bloated" (n_fights > 12)
    """
    flags = []
    if n_fights == 0:
        # Empty card — no health checks apply (projection shows the
        # "no pulse" voice phrase; no need to flag empty too).
        return flags

    # 1. Main event weaker than co-main.
    if me_mkt < co_mkt and co_mkt > 0:
        gap = co_mkt - me_mkt
        if gap >= 10:
            flags.append({
                "flag": "main_weaker_than_comain",
                "severity": "warning",
                "phrase": "Your co-main outshines the main event — fans will notice.",
            })

    # 2. No title fight on a PPV.
    ev_row = conn.execute(
        "SELECT is_ppv FROM events WHERE event_id=?", (event_id,),
    ).fetchone()
    is_ppv = bool(ev_row and ev_row[0])
    if is_ppv and n_title == 0:
        flags.append({
            "flag": "no_title_on_ppv",
            "severity": "warning",
            "phrase": "PPV card with no title fight — the buyrate will suffer.",
        })

    # 3. Card has 0 hometown fighters.
    hometown_count = _count_hometown_fighters_on_card(conn, event_id)
    if hometown_count == 0 and n_fights >= 3:
        flags.append({
            "flag": "no_hometown_fighters",
            "severity": "info",
            "phrase": "No hometown fighters on the card — the local crowd has no horse in the race.",
        })

    # 4. Main event fighter on cold streak.
    me_row = conn.execute(
        "SELECT fi.fighter_id, fc.loss_streak "
        "FROM fights f "
        "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
        "  AND fp.corner='red' "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id=fi.fighter_id "
        "WHERE f.event_id=? AND f.card_slot='main_event' "
        "LIMIT 1",
        (event_id,),
    ).fetchone()
    if me_row and me_row[1] is not None and me_row[1] >= 2:
        flags.append({
            "flag": "main_event_cold_streak",
            "severity": "warning",
            "phrase": "Main event fighter comes in on a cold streak — the air is out of the matchup.",
        })

    # 5. Style diversity — 4+ fights with the same archetype.
    style_counts = {}
    style_rows = conn.execute(
        "SELECT sa.name "
        "FROM fights f "
        "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "LEFT JOIN style_archetypes sa "
        "  ON sa.style_archetype_id=fi.fight_style_archetype_id "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchall()
    for (sname,) in style_rows:
        if sname:
            style_counts[sname] = style_counts.get(sname, 0) + 1
    if style_counts:
        top_style, top_count = max(style_counts.items(), key=lambda x: x[1])
        # 4+ of same style on a card with at least 5 fights = diversity issue.
        if top_count >= 4 and n_fights >= 5:
            flags.append({
                "flag": "low_style_diversity",
                "severity": "info",
                "phrase": f"Card leans heavily on {top_style.lower()}s — a stylistic change of pace is missing.",
            })

    # 6. Card is too thin / too bloated.
    if n_fights < 4:
        flags.append({
            "flag": "card_too_thin",
            "severity": "info",
            "phrase": "Card is thin — fans expect at least four bouts.",
        })
    elif n_fights > 12:
        flags.append({
            "flag": "card_too_bloated",
            "severity": "info",
            "phrase": "Card is bloated — late prelims will be lost in the shuffle.",
        })

    return flags


def _count_hometown_fighters_on_card(conn, event_id):
    """Count fighters on the card whose birth_nation matches the
    event venue's nation. A loose proxy for "hometown fighter" —
    the spec asks for "hometown reaction" which we interpret as
    "fighter is from the same country as the event venue" (city-level
    would be too narrow given the seed's fighter distribution).
    """
    row = conn.execute(
        "SELECT n.nation_id "
        "FROM events e "
        "JOIN venues v ON v.venue_id=e.venue_id "
        "JOIN cities c ON c.city_id=v.city_id "
        "LEFT JOIN nations n ON n.nation_id=c.nation_id "
        "WHERE e.event_id=?",
        (event_id,),
    ).fetchone()
    if not row or row[0] is None:
        return 0
    venue_nation = row[0]
    cnt = conn.execute(
        "SELECT COUNT(DISTINCT fi.fighter_id) "
        "FROM fights f "
        "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
        "JOIN fighters fi ON fi.fighter_id=fp.fighter_id "
        "WHERE f.event_id=? AND fi.birth_nation_id=?",
        (event_id, venue_nation),
    ).fetchone()
    return int(cnt[0] or 0) if cnt else 0


def _voice_kind_for_net(net_profit, current_cash):
    """Classify a projected net profit into the voice_kind buckets
    used by the Event Builder preview (safe / risky / lethal).

    Mirrors the existing logic in `get_event_preview` lines 2918-2926.
    """
    if net_profit >= 0:
        return ("safe", "Your war chest can absorb this.")
    if current_cash > abs(net_profit):
        return ("risky", "You're betting the farm on this card.")
    return ("lethal", "This could bankrupt you. Are you sure?")


def _voice_kind_for_net_range(net_low, net_high, current_cash):
    """Phase F1.3 — classify a projected net-profit RANGE into the
    voice_kind buckets (safe / risky / lethal) + voice phrase.

    Pre-event, show quality is unknown. Revenue varies ±30% based on
    how the show actually performs. So we have a low end (terrible
    show) and a high end (blockbuster). The voice phrase reflects the
    range shape:

      - both positive + high (net_low > 200k AND net_high > 0):
        safe / "This card should bring in serious money — if the
        fights deliver."
      - both positive but tight (net_low > 0 AND net_high > 0):
        safe / "Modest profit expected. The fights need to be good
        to justify the card."
      - spans zero (net_low < 0 AND net_high > 0):
        risky / "This is a gamble. A great show makes money, a bad
        one loses it."
      - both negative (net_high < 0):
        lethal / "You're losing money on this one. Reconsider the
        card or the levers."

    The current_cash arg is retained for future use (bankruptcy-risk
    voice layer) but the F1.3 phrases don't use it — the range itself
    is the primary signal.
    """
    if net_low > 200000 and net_high > 0:
        return ("safe",
                "This card should bring in serious money — if the "
                "fights deliver.")
    if net_low > 0 and net_high > 0:
        return ("safe",
                "Modest profit expected. The fights need to be good "
                "to justify the card.")
    if net_low < 0 and net_high > 0:
        return ("risky",
                "This is a gamble. A great show makes money, a bad "
                "one loses it.")
    if net_high <= 0:
        # Both ends non-positive — losing money even on a great show.
        # Override to lethal if the loss would wipe the war chest.
        if current_cash is not None and current_cash < abs(net_low):
            return ("lethal",
                    "You're losing money on this one — and your war "
                    "chest can't absorb it. Reconsider the card or "
                    "the levers.")
        return ("lethal",
                "You're losing money on this one. Reconsider the "
                "card or the levers.")
    # Fallback (shouldn't happen — covers net_low==0 / net_high==0).
    return ("safe",
            "Your war chest can absorb this.")


# ============================================================
# THE PYTHON API — exposed to JS as window.pywebview.api.*
# ============================================================

class Api:
    """The Python API exposed to JS via pywebview.

    Every method returns JSON-serializable Python objects (dicts, lists,
    strings, numbers). pywebview serializes them transparently to JS.

    Per CONVENTIONS §14 + §17:
      - Fighter data comes from `fighter_descriptors` (the cache), not
        raw attribute tables.
      - Voice phrases ('label||phrase') are returned AS-IS to JS — the
        JS side decodes them via bridge helpers.
    """

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        # CRITICAL: pywebview calls API methods from different threads
        # (WebView2/EdgeChromium spawns threads for JS↔Python calls).
        # SQLite connections default to check_same_thread=True which
        # raises "SQLite objects created in a thread can only be used
        # in that same thread". We disable the check + enable WAL mode
        # which handles concurrent access safely (multiple readers,
        # serialized writers).
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA busy_timeout = 5000;")
        # Register every event-bus subscriber so Advance Day actually
        # runs the simulation (retirements, injuries, scouting, rival
        # AI, news, auto-save, interpretation refresh, etc.).
        register_all_subscribers()

    # ============================================================
    # CLOCK + PLAYER SETTINGS
    # ============================================================

    def get_clock(self):
        """Return the current sim clock as a dict.

        Includes month_name (English) so the JS side doesn't have to
        implement its own month-name lookup.
        """
        try:
            c = get_clock(self.conn)
            if not c:
                return None
            month = c[3]
            month_name = calendar.month_name[month] if isinstance(month, int) and 1 <= month <= 12 else ""
            return {
                "current_date": c[0],
                "current_day": c[1],
                "current_week": c[2],
                "current_month": month,
                "current_year": c[4] if c[4] else 1,
                "tick_counter": c[5],
                "month_name": month_name,
            }
        except Exception as e:
            print(f"[api.get_clock] {e}", flush=True)
            return None

    def get_player_promotion(self):
        """Return the player's selected promotion_id (int) or 0 if unselected.

        Persisted in the `player_settings` table under the key
        'player_promotion_id' so it survives app restarts. We read it
        with a direct SQL query (rather than player_settings.get_setting)
        because the helper validates against DEFAULT_SETTINGS, which
        doesn't include 'player_promotion_id'.
        """
        try:
            row = self.conn.execute(
                "SELECT setting_value FROM player_settings WHERE setting_key=?",
                ("player_promotion_id",)
            ).fetchone()
            if not row or not row[0]:
                return 0
            return int(row[0])
        except Exception:
            return 0

    # ============================================================
    # PHASE 5 TASK 3 — PLAYER WATCHLIST
    # Minimal watchlist piggybacking on the existing player_decisions
    # table. Two new decision_types ('watch' / 'unwatch') relax the
    # original v3.16.0 CHECK constraint (see migration
    # _migrate_v3_37_0_relax_player_decisions_watchlist_check in
    # build_db.py). A fighter is "currently watched" if their most
    # recent 'watch'/'unwatch' decision is 'watch'. Cap: 12 per promo.
    # Voice compliance (CONVENTIONS §14): uses fighter_descriptors for
    # momentum (label||phrase), NEVER raw attribute numbers.
    # ============================================================

    # Watchlist cap — per docs/PHASE5_UI_POLISH_PLAN.md Task 3 spec.
    WATCHLIST_CAP = 12

    def _watched_fighter_ids_for_promo(self, promo_id, limit=None):
        """Return a list of (fighter_id, watched_since_date) tuples for
        currently-watched fighters on `promo_id`, newest-watch-first.

        "Currently watched" = the fighter's most recent 'watch'/
        'unwatch' decision is 'watch' (i.e. there's no later 'unwatch'
        row for the same fighter_id). Limited to `limit` rows (default
        WATCHLIST_CAP) so the Dashboard / Fighter Profile / Roster
        screens don't pull the entire history.

        IMPORTANT: the "later" comparator is `decision_id`, NOT
        `decision_date`. The sim clock advances one day at a time, so
        multiple decisions taken on the same sim day share the same
        `decision_date` string. If we compared on `decision_date`, a
        same-day watch→unwatch pair (e.g. user toggles ★ on then off
        without advancing the day) would look like two equal-date
        rows + the unwatch wouldn't override the watch. Using
        `decision_id` (AUTOINCREMENT primary key) gives a strict
        monotonic order that matches actual insert order.

        The "latest decision per fighter" sub-query (pd.decision_id =
        MAX over watch+unwatch rows for the same fighter) ensures each
        fighter is counted ONCE even if they have multiple 'watch'
        rows in their history (e.g. watched, unwatched, re-watched —
        only the latest decision matters, so we get 1 row, not 2).
        Without this, the cap check would over-count + reject valid
        re-watches.

        Returns an empty list on any error (defensive — caller should
        treat as "no watched fighters").
        """
        try:
            if not promo_id:
                return []
            cap = limit if limit is not None else self.WATCHLIST_CAP
            sql = (
                "SELECT pd.target_fighter_id, pd.decision_date "
                "FROM player_decisions pd "
                "WHERE pd.decision_type = 'watch' "
                "  AND pd.target_fighter_id IS NOT NULL "
                "  AND pd.target_fighter_id IN ("
                "      SELECT fighter_id FROM fighters "
                "      WHERE current_promotion_id = ?"
                "  ) "
                # The fighter's LATEST decision (watch or unwatch)
                # must be this 'watch' row — i.e. no later row of
                # EITHER type exists for the same fighter. This
                # correctly handles the same-day watch→unwatch→watch
                # cycle (only the most recent watch counts) AND
                # avoids duplicate rows when a fighter has been
                # watched multiple times in their history.
                "  AND NOT EXISTS ("
                "      SELECT 1 FROM player_decisions pd2 "
                "      WHERE pd2.target_fighter_id = pd.target_fighter_id "
                "        AND pd2.decision_type IN ('watch','unwatch') "
                "        AND pd2.decision_id > pd.decision_id"
                "  ) "
                "ORDER BY pd.decision_date DESC, pd.decision_id DESC "
                "LIMIT ?"
            )
            rows = self.conn.execute(sql, (int(promo_id), int(cap))).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception as e:
            print(f"[api._watched_fighter_ids_for_promo] {e}", flush=True)
            return []

    def _is_fighter_currently_watched(self, fighter_id):
        """Return True if `fighter_id` has a 'watch' decision with no
        later 'unwatch' decision. Used by get_fighter_profile_data to
        populate the `is_watched` header field without re-querying the
        full watchlist.

        Uses `decision_id` (AUTOINCREMENT) as the "later" comparator
        instead of `decision_date` — see the docstring on
        _watched_fighter_ids_for_promo for the same-day rationale.

        The check is "the fighter's latest decision is a watch" — so
        a watch→unwatch→watch cycle (all on the same sim day) leaves
        the fighter watched, and a watch→unwatch leaves them not
        watched. Multiple consecutive watch rows (no unwatch between)
        are collapsed to a single "watched" result."""
        try:
            fid = int(fighter_id)
            # Find the fighter's latest 'watch' or 'unwatch' decision
            # by decision_id. If it's a 'watch', they're currently
            # watched. (This is one row + one comparison, faster than
            # the NOT EXISTS pattern when called per-fighter.)
            row = self.conn.execute(
                "SELECT decision_type FROM player_decisions "
                "WHERE target_fighter_id = ? "
                "  AND decision_type IN ('watch','unwatch') "
                "ORDER BY decision_id DESC LIMIT 1",
                (fid,),
            ).fetchone()
            return bool(row) and row[0] == 'watch'
        except Exception:
            return False

    def add_to_watchlist(self, fighter_id, reason='manual'):
        """Add `fighter_id` to the player's watchlist.

        Validates:
          - fighter_id exists in the fighters table
          - fighter is currently on the player's promotion (you can
            only watch your own roster)
          - the watchlist cap (12 per promo) isn't already met — i.e.
            there are fewer than 12 currently-watched fighters on the
            player's promo. If the cap is met, returns
            {ok: false, error: "Watchlist full (max 12)"}.

        On success, INSERTs a 'watch' row into player_decisions with
        context_json = {"reason": <reason>, "added_at": <sim_date>}.

        Idempotency: this method does NOT check whether the fighter is
        already watched. If called twice in a row, two 'watch' rows
        are inserted — but _is_fighter_currently_watched + get_watchlist
        only consider the LATEST 'watch'/'unwatch' pair, so the second
        call is effectively a no-op from the player's POV. (The cap
        check counts only currently-watched fighters, so a double-add
        won't push the count over 12.)
        """
        try:
            fid = int(fighter_id)
            player_promo = self.get_player_promotion()
            if not player_promo:
                return {"ok": False,
                        "error": "No promotion selected — pick a promotion first."}

            # 1. Validate fighter exists + is on the player's promo.
            f = self.conn.execute(
                "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if not f:
                return {"ok": False,
                        "error": f"Fighter {fid} not found"}
            if f[0] != player_promo:
                return {"ok": False,
                        "error": "Can only watch fighters on your promotion"}

            # 2. Cap check — count currently-watched fighters on this
            # promo (the fighter about to be watched doesn't count
            # toward the cap yet, but if they're already watched this
            # call is a re-affirmation, so we permit it through).
            already_watched = self._is_fighter_currently_watched(fid)
            if not already_watched:
                current_count = len(
                    self._watched_fighter_ids_for_promo(player_promo)
                )
                if current_count >= self.WATCHLIST_CAP:
                    return {"ok": False,
                            "error": f"Watchlist full (max {self.WATCHLIST_CAP})"}

            # 3. Determine decision_date from sim clock.
            clock = get_clock(self.conn)
            sim_date = clock[0] if clock else None
            if not sim_date:
                return {"ok": False,
                        "error": "Simulation clock is missing — cannot log watch decision"}

            # 4. INSERT the 'watch' row.
            context = {
                "reason": str(reason or "manual"),
                "added_at": sim_date,
                "promo_id": int(player_promo),
            }
            from player_decisions import log_decision, TYPE_WATCH
            decision_id = log_decision(
                self.conn,
                decision_type=TYPE_WATCH,
                target_fighter_id=fid,
                target_promo_id=int(player_promo),
                context=context,
                decision_date=sim_date,
            )
            if not decision_id:
                return {"ok": False,
                        "error": "Failed to insert watch decision (see server log)"}
            self.conn.commit()
            return {"ok": True, "fighter_id": fid}
        except Exception as e:
            print(f"[api.add_to_watchlist] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def remove_from_watchlist(self, fighter_id, reason='manual'):
        """Remove `fighter_id` from the player's watchlist.

        Validates: fighter_id exists (we don't check promo — removing
        a fighter that's already not watched is a no-op per the spec's
        idempotency requirement).

        On success, INSERTs an 'unwatch' row into player_decisions
        with context_json = {"reason": <reason>}. This OVERRIDES any
        prior 'watch' row for the same fighter (the
        _is_fighter_currently_watched helper checks for a later
        'unwatch' decision).

        Idempotency: per the spec, this method does NOT error if the
        fighter wasn't currently watched. It just adds an 'unwatch'
        row, which is a no-op if there's no prior 'watch'.
        """
        try:
            fid = int(fighter_id)

            # 1. Validate fighter exists.
            f = self.conn.execute(
                "SELECT fighter_id FROM fighters WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if not f:
                return {"ok": False,
                        "error": f"Fighter {fid} not found"}

            # 2. Determine decision_date from sim clock.
            clock = get_clock(self.conn)
            sim_date = clock[0] if clock else None
            if not sim_date:
                return {"ok": False,
                        "error": "Simulation clock is missing — cannot log unwatch decision"}

            # 3. INSERT the 'unwatch' row (idempotent — always inserts
            # a new row, even if the fighter wasn't currently watched).
            player_promo = self.get_player_promotion()
            context = {"reason": str(reason or "manual")}
            if player_promo:
                context["promo_id"] = int(player_promo)
            from player_decisions import log_decision, TYPE_UNWATCH
            decision_id = log_decision(
                self.conn,
                decision_type=TYPE_UNWATCH,
                target_fighter_id=fid,
                target_promo_id=int(player_promo) if player_promo else None,
                context=context,
                decision_date=sim_date,
            )
            if not decision_id:
                return {"ok": False,
                        "error": "Failed to insert unwatch decision (see server log)"}
            self.conn.commit()
            return {"ok": True, "fighter_id": fid}
        except Exception as e:
            print(f"[api.remove_from_watchlist] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_watchlist(self, promo_id=None):
        """Return the currently-watched fighters for `promo_id`.

        If `promo_id` is None, uses the player's selected promotion.

        Returns a list of up to 12 dicts (one per currently-watched
        fighter), each shaped like:
            {
                "fighter_id": 5,
                "name": "John Smith",
                "weight_class_name": "Heavyweight",
                "portrait_b64": "<b64 string>" or null,
                "momentum_phrase": "riding a hot streak",
                "momentum_label": "very_high",
                "record": "15-2-0",
                "is_champion": false,
                "watched_since": "2026-08-17"
            }

        Voice compliance (CONVENTIONS §14): momentum_phrase + label
        come from fighter_descriptors (decoded via _decode_phrase /
        _decode_label). NO raw attribute numbers are returned.

        Returns an empty list if the promo has no watched fighters,
        if the promo_id is invalid, or if no player promotion is
        selected (when promo_id=None).
        """
        try:
            if promo_id is None:
                pid = self.get_player_promotion()
            else:
                pid = int(promo_id)
            if not pid:
                return []

            # 1. Pull the currently-watched fighter_ids (capped at
            # WATCHLIST_CAP) — newest watch first.
            watched = self._watched_fighter_ids_for_promo(pid)
            if not watched:
                return []

            watched_map = {fid: since for fid, since in watched}
            fid_list = list(watched_map.keys())

            # 2. Champion fighter_ids for this promo (used to populate
            # is_champion without a per-fighter sub-query).
            champ_ids = set()
            for r in self.conn.execute(
                "SELECT current_champion_fighter_id FROM titles "
                "WHERE promotion_id=? AND is_vacant=0 "
                "  AND current_champion_fighter_id IS NOT NULL",
                (pid,),
            ).fetchall():
                champ_ids.add(r[0])

            # 3. Bulk-fetch fighter + descriptor data for all watched
            # fighter_ids in one query (avoids N+1 pattern).
            placeholders = ",".join(["?"] * len(fid_list))
            rows = self.conn.execute(
                "SELECT f.fighter_id, f.first_name, f.last_name, "
                "  f.portrait_path, "
                "  wc.name AS wc_name, "
                "  fd.momentum, fd.momentum_short, "
                "  fc.record_wins, fc.record_losses, fc.record_draws "
                "FROM fighters f "
                "LEFT JOIN weight_classes wc "
                "  ON wc.weight_class_id = f.weight_class_id "
                "LEFT JOIN fighter_descriptors fd "
                "  ON fd.fighter_id = f.fighter_id "
                "LEFT JOIN fighter_career fc "
                "  ON fc.fighter_id = f.fighter_id "
                "WHERE f.fighter_id IN (" + placeholders + ")",
                fid_list,
            ).fetchall()

            # 4. Build the response list, preserving watch-order (newest
            # watch first — watched_map was built in that order).
            #
            # SELECT column → row index map:
            #   0 fighter_id        1 first_name         2 last_name
            #   3 portrait_path     4 wc_name            5 momentum (LONG)
            #   6 momentum_short    7 record_wins        8 record_losses
            #   9 record_draws
            by_id = {}
            for r in rows:
                fid = r[0]
                # Label from LONG form (canonical momentum tier) —
                # falls back to SHORT label if LONG is NULL.
                momentum_label = (_decode_label(r[5]) if r[5]
                                  else (_decode_label(r[6]) if r[6] else ""))
                # Phrase prefers LONG (descriptive) — matches the
                # Fighter Watch card voice style on the Dashboard.
                momentum_phrase = (_decode_phrase(r[5]) if r[5]
                                   else (_decode_phrase(r[6]) if r[6] else ""))
                record_str = f"{r[7] or 0}-{r[8] or 0}-{r[9] or 0}"

                # Portrait — reuse the cached loader (in-memory cache
                # survives across calls in the same Api instance).
                portrait_b64 = None
                if r[3]:  # portrait_path
                    p = self.get_fighter_portrait_b64(fid)
                    if p and p.get("has_portrait"):
                        portrait_b64 = p.get("portrait_b64")

                by_id[fid] = {
                    "fighter_id": fid,
                    "name": f"{r[1]} {r[2]}",
                    "weight_class_name": r[4] or "—",
                    "portrait_b64": portrait_b64,
                    "momentum_phrase": momentum_phrase,
                    "momentum_label": momentum_label,
                    "record": record_str,
                    "is_champion": fid in champ_ids,
                    "watched_since": watched_map.get(fid, ""),
                }

            # Preserve the watched order (newest first).
            out = []
            for fid in fid_list:
                if fid in by_id:
                    out.append(by_id[fid])
            return out
        except Exception as e:
            print(f"[api.get_watchlist] {e}\n{traceback.format_exc()}",
                  flush=True)
            return []

    # ============================================================
    # HW2.4 — WORLD HEALTH STATUS (W27)
    # ============================================================

    def get_world_health(self):
        """HW2.4: return the cached world health status (HEALTHY /
        DEGRADED / BROKEN) + the 4 signals that produced it.

        The status is recomputed on each monthly tick (current_day %
        30 == 0) by the _world_health_monthly_subscriber registered
        in _register_default_subscribers. Between monthly ticks, the
        cached result is returned (so this is a cheap call safe to
        poll from JS).

        Returns:
            dict with keys:
                status: 'HEALTHY' | 'DEGRADED' | 'BROKEN'
                signals: dict of {db_integrity, recent_tick_health,
                                   event_resolution_rate,
                                   finance_activity} — each with
                                   'value' + 'detail'
                sim_date: the sim date the status was computed for
                computed_at: ISO timestamp when the computation ran
        """
        try:
            from tick_processor import (
                get_world_health_cache, compute_world_health,
            )
            cached = get_world_health_cache()
            # If the cache is empty (no monthly tick has fired yet),
            # compute on-demand so the UI has a real answer on first
            # load. This is a one-time cost — subsequent calls hit the
            # cache populated by the monthly subscriber.
            if not cached.get('computed_at'):
                return compute_world_health(self.conn)
            return cached
        except Exception as e:
            print(f"[api.get_world_health] {e}", flush=True)
            return {
                'status': 'BROKEN',
                'signals': {},
                'sim_date': None,
                'computed_at': None,
                'error': str(e),
            }

    def select_promotion(self, promo_id):
        """Set the player's selected promotion. Returns {ok, promo_id}.

        Writes directly to the player_settings table (INSERT OR REPLACE)
        rather than via player_settings.set_setting, because the helper
        refuses keys not in DEFAULT_SETTINGS — and 'player_promotion_id'
        is a UI-layer setting, not a game-balance setting.

        PHASE-R (Reward Layer §6 Principle 4): on first promo selection
        we also backfill the player_decisions log with synthesized
        sign/cut decisions from the promo's existing roster + terminated
        contracts. This ensures the Echoes section + per-fighter
        "Your History" section aren't empty on the first Advance Day.
        The backfill is idempotent — a marker row prevents re-runs.
        """
        try:
            pid = int(promo_id)
            self.conn.execute(
                "INSERT OR REPLACE INTO player_settings "
                "(setting_key, setting_value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                ("player_promotion_id", str(pid)),
            )
            # PHASE-R: backfill player_decisions for this promo (sign
            # decisions for the current roster + cut decisions for
            # terminated contracts of fighters now free agents).
            # Idempotent — safe to call on every select_promotion.
            try:
                from player_decisions import (
                    backfill_player_decisions_for_promo,
                )
                result = backfill_player_decisions_for_promo(self.conn, pid)
                if not result.get("skipped"):
                    print(f"[app_web] Backfilled player_decisions for "
                          f"promo {pid}: "
                          f"{result.get('signs_backfilled', 0)} signs, "
                          f"{result.get('cuts_backfilled', 0)} cuts",
                          flush=True)
            except Exception as e:
                print(f"[app_web] WARN: player_decisions backfill "
                      f"failed: {e}", flush=True)
            self.conn.commit()
            return {"ok": True, "promo_id": pid}
        except Exception as e:
            print(f"[api.select_promotion] {e}", flush=True)
            return {"ok": False, "error": str(e)}

    def set_player_name(self, name):
        """Set the player's manager name. Stored in player_settings."""
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO player_settings "
                "(setting_key, setting_value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                ("player_name", str(name).strip()[:100]),
            )
            self.conn.commit()
            return {"ok": True, "name": str(name).strip()}
        except Exception as e:
            print(f"[api.set_player_name] {e}", flush=True)
            return {"ok": False, "error": str(e)}

    def get_player_name(self):
        """Return the player's manager name, or empty string."""
        try:
            row = self.conn.execute(
                "SELECT setting_value FROM player_settings WHERE setting_key=?",
                ("player_name",)
            ).fetchone()
            return row[0] if row and row[0] else ""
        except Exception:
            return ""

    def get_player_cash(self):
        """Return {cash, cash_display, is_negative} for the player's promo."""
        try:
            pid = self.get_player_promotion()
            if not pid:
                return None
            row = self.conn.execute(
                "SELECT current_cash FROM promotions WHERE promotion_id=?",
                (pid,)
            ).fetchone()
            if not row:
                return None
            cash = float(row[0] or 0)
            return {
                "cash": cash,
                "cash_display": _format_cash(cash),
                "is_negative": cash < 0,
            }
        except Exception as e:
            print(f"[api.get_player_cash] {e}", flush=True)
            return None

    def get_promotion_list(self):
        """Return the list of all promotions for the startup selection screen."""
        try:
            rows = self.conn.execute("""SELECT promotion_id, name, current_cash,
                reputation, fan_trust, size_tier, broadcast_tier
                FROM promotions ORDER BY promotion_id""").fetchall()
            out = []
            for r in rows:
                out.append({
                    "promotion_id": r[0],
                    "name": r[1],
                    "current_cash": float(r[2] or 0),
                    "reputation": r[3],
                    "fan_trust": r[4],
                    "size_tier": r[5] or "",
                    "broadcast_tier": r[6] or "",
                    "logo_b64": _load_logo_b64(r[0]),
                })
            return out
        except Exception as e:
            print(f"[api.get_promotion_list] {e}", flush=True)
            return []

    # ============================================================
    # DASHBOARD — full live-data payload
    # ============================================================

    def get_dashboard_data(self, promo_id):
        """Return the full dashboard payload for `promo_id`.

        Mirrors the data-gathering logic in scripts/generate_dashboard_html.py
        but returns a dict instead of generating HTML. The JS dashboard
        renderer (src/web/js/dashboard.js) consumes this dict.

        Per CONVENTIONS §17: reads from cache tables (daily_headlines,
        fighter_descriptors) for fighter interpretation data + game-
        state tables (promotions, titles, news_items, events) for non-
        fighter data. NEVER reads fighter_attributes / fighter_personality.
        """
        try:
            pid = int(promo_id)
            conn = self.conn

            # 1. Clock + promo info
            c = get_clock(conn)
            sim_date = c[0]
            month = c[3]
            year = c[4] if c[4] else 1
            month_name = calendar.month_name[month] if isinstance(month, int) and 1 <= month <= 12 else ""

            promo = conn.execute("""SELECT name, current_cash, reputation, fan_trust,
                size_tier, broadcast_tier FROM promotions WHERE promotion_id=?""",
                (pid,)).fetchone()
            if not promo:
                return {"error": f"Promotion {pid} not found"}
            promo_name = promo[0]
            cash = float(promo[1] or 0)
            rep = promo[2] or 0
            fan_trust = promo[3] or 0
            size_tier = (promo[4] or "").upper()
            broadcast = (promo[5] or "").upper()

            # 2. Top story (most recent daily_headlines top_story)
            ts = conn.execute("""SELECT headline_text, body_text, fighter_id
                FROM daily_headlines WHERE headline_type='top_story'
                ORDER BY headline_date DESC LIMIT 1""").fetchone()
            ts_fighter_name = ""
            ts_fighter_id = None
            if ts and ts[2]:
                f = conn.execute("SELECT first_name, last_name FROM fighters WHERE fighter_id=?",
                                 (ts[2],)).fetchone()
                if f:
                    ts_fighter_name = f"{f[0]} {f[1]}"
                    ts_fighter_id = ts[2]
            top_story = {
                "headline": ts[0] if ts else "The newswire is quiet.",
                "body": ts[1] if ts and ts[1] else "No stories have broken in the last 24 hours. Advance a day to see what develops.",
                "fighter_id": ts_fighter_id,
                "fighter_name": ts_fighter_name,
                "topic": "wire",
            }

            # 2b. Echoes — Phase R §1.5 + §6 Principle 4.
            # Read up to 3 daily_echoes rows for the player's promo.
            # Falls back to most-recent-date rows if no echoes exist
            # for today (e.g. on first load before any Advance Day).
            # Each echo carries: phrase, echo_type, target_fighter_id
            # (for hyperlink), link_to_screen (which screen to navigate
            # to on click), fighter_name (resolved here so the JS side
            # doesn't have to do another round-trip).
            #
            # HW3.4 audit fix: filter MAX(echo_date) to echo_date <=
            # sim_date so future-dated echoes from a reverted forward-
            # sim can't dominate the dashboard. The echoes_engine also
            # cleans these up on every Advance Day (defensive), but
            # this query-level filter is belt-and-suspenders.
            echo_rows = conn.execute("""SELECT de.echo_date, de.echo_slot,
                de.echo_type, de.phrase, de.decision_id,
                de.target_fighter_id, de.link_to_screen,
                f.first_name, f.last_name
                FROM daily_echoes de
                LEFT JOIN fighters f ON f.fighter_id = de.target_fighter_id
                WHERE de.echo_date = (
                    SELECT MAX(echo_date) FROM daily_echoes
                    WHERE echo_date <= ?
                )
                ORDER BY de.echo_slot LIMIT 3""", (sim_date,)).fetchall()
            echoes = []
            for er in echo_rows:
                fid = er[5]
                fname = f"{er[7]} {er[8]}" if er[7] else None
                echoes.append({
                    "echo_type": er[2],
                    "phrase": er[3] or "",
                    "decision_id": er[4],
                    "target_fighter_id": fid,
                    "fighter_name": fname,
                    "link_to_screen": er[6] or "fighter_profile",
                })

            # 3. Fighter watch (3 cards: TOP PROSPECT, HOTTEST STREAK, BIGGEST FALL)
            watch = []
            seen_ids = set()
            for htype, label, accent in [
                ("fastest_rising", "TOP PROSPECT", "gold"),
                ("fastest_rising", "HOTTEST STREAK", "gold"),
                ("biggest_fall", "BIGGEST FALL", "crimson"),
            ]:
                fid = None
                if label == "HOTTEST STREAK":
                    # Find a very_high-momentum fighter NOT already in the watch list
                    # CR-5: filter to player's promo (was surfacing rival fighters)
                    excluded = ",".join(str(x) for x in seen_ids) if seen_ids else "0"
                    hot = conn.execute(f"""SELECT f.fighter_id FROM fighters f
                        JOIN fighter_descriptors fd ON fd.fighter_id=f.fighter_id
                        WHERE fd.momentum LIKE 'very_high||%' AND f.is_active=1
                        AND f.current_promotion_id=?
                        AND f.fighter_id NOT IN ({excluded})
                        ORDER BY f.fighter_id LIMIT 1""", (pid,)).fetchone()
                    if hot:
                        fid = hot[0]
                else:
                    # CR-5: filter daily_headlines by joining fighters + checking
                    # current_promotion_id so rival-promo prospects/falls don't
                    # surface in "WHO'S MAKING MOVES FOR YOU".
                    h = conn.execute("""SELECT dh.fighter_id FROM daily_headlines dh
                        JOIN fighters f ON f.fighter_id = dh.fighter_id
                        WHERE dh.headline_type=? AND f.current_promotion_id=? AND f.is_active=1
                        ORDER BY dh.headline_date DESC LIMIT 1""",
                        (htype, pid)).fetchone()
                    if h and h[0]:
                        fid = h[0]
                if not fid or fid in seen_ids:
                    continue
                seen_ids.add(fid)

                f = conn.execute("""SELECT f.first_name, f.last_name,
                    fd.momentum, fd.momentum_short,
                    fd.career_phase, fd.career_phase_short,
                    fd.narrative_family, fd.narrative_family_short,
                    fd.pressure, fd.pressure_short,
                    fd.legacy_state, fd.legacy_state_short
                    FROM fighters f
                    LEFT JOIN fighter_descriptors fd ON fd.fighter_id=f.fighter_id
                    WHERE f.fighter_id=?""", (fid,)).fetchone()
                if not f:
                    continue
                fights = conn.execute("""SELECT outcome FROM fight_history
                    WHERE fighter_id=? ORDER BY event_date DESC LIMIT 5""",
                    (fid,)).fetchall()
                last5 = [r[0][0].upper() if r[0] else "N" for r in fights]
                # Pad to 5 if fewer
                while len(last5) < 5:
                    last5.append("N")

                watch.append({
                    "label": label,
                    "accent": accent,
                    "fighter_id": fid,
                    "name": f"{f[0]} {f[1]}",
                    # Use SHORT phrases for watch cards (≤25 chars, no overflow)
                    "momentum_label": _decode_label(f[2]),
                    "momentum_phrase": _decode_phrase(f[3]) if f[3] else _decode_phrase(f[2]),
                    "career_phase": _decode_phrase(f[5]) if f[5] else _decode_phrase(f[4]),
                    "narrative": _decode_phrase(f[7]) if f[7] else (_decode_phrase(f[6]) if f[6] else None),
                    "pressure": _decode_phrase(f[9]) if f[9] else (_decode_phrase(f[8]) if f[8] else None),
                    # Also include full phrases for hover/tooltips
                    "momentum_phrase_full": _decode_phrase(f[2]),
                    "career_phase_full": _decode_phrase(f[4]),
                    "last5": last5,
                })

            # 4. Champions (titles for this promo)
            champs_rows = conn.execute("""SELECT wc.name, f.fighter_id, f.first_name, f.last_name,
                t.champion_since_date, t.title_reigns_count, t.title_defenses_count
                FROM titles t JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id
                LEFT JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id
                WHERE t.promotion_id=? AND t.is_vacant=0 AND t.current_champion_fighter_id IS NOT NULL
                ORDER BY COALESCE(wc.display_order, wc.weight_class_id)""", (pid,)).fetchall()
            champions = [{
                "weight_class": c[0],
                "fighter_id": c[1],
                "name": f"{c[2]} {c[3]}",
                "champion_since_date": c[4],
                "title_reigns_count": c[5] or 1,
                "title_defenses_count": c[6] or 0,
            } for c in champs_rows]

            # 5. Recent news (5 most recent)
            news_rows = conn.execute("""SELECT headline, body, topic, fighter_id, published_at
                FROM news_items ORDER BY published_at DESC LIMIT 5""").fetchall()
            recent_news = [{
                "headline": n[0],
                "body": n[1] or "",
                "topic": n[2] or "wire",
                "fighter_id": n[3],
                "published_at": n[4] or "",
            } for n in news_rows]

            # 6. Recent results (3 most recent completed events for THIS promo)
            # CR-6: filter to player's promo + limit 3 (was 4, no promo filter)
            recent_rows = conn.execute("""SELECT p.name, e.event_date, e.event_name,
                sr.overall_rating, sr.rating_description
                FROM events e JOIN promotions p ON p.promotion_id=e.promotion_id
                LEFT JOIN show_ratings sr ON sr.event_id=e.event_id
                WHERE e.status='completed' AND e.promotion_id=?
                ORDER BY e.event_date DESC LIMIT 3""", (pid,)).fetchall()
            recent_results = [{
                "promo_name": r[0] or "",
                "event_date": r[1] or "",
                "event_name": r[2] or "",
                "overall_rating": r[3],
                "rating_description": r[4] or "",
            } for r in recent_rows]

            # 7. Next event (next scheduled event for THIS promo — not all promos)
            next_row = conn.execute("""SELECT e.event_id, p.name, e.event_date, e.event_name
                FROM events e JOIN promotions p ON p.promotion_id=e.promotion_id
                WHERE e.status IN ('scheduled', 'card_confirmed') AND e.promotion_id=?
                ORDER BY e.event_date LIMIT 1""", (pid,)).fetchone()
            next_event = None
            if next_row:
                next_event = {
                    "event_id": next_row[0],
                    "promo_name": next_row[1],
                    "event_date": next_row[2],
                    "event_name": next_row[3] or "",
                }

            # P-FIX: Upcoming events — ALL scheduled events for the player's
            # promo, with fight counts + card status. The player needs a clear
            # way to see confirmed/booked events (per user feedback: "currently
            # there's no way to see them again once you leave the matchmaking screen").
            upcoming_rows = conn.execute("""SELECT e.event_id, e.event_date, e.event_name,
                e.status,
                (SELECT COUNT(*) FROM fights f WHERE f.event_id = e.event_id) as fight_count
                FROM events e
                WHERE e.status IN ('scheduled', 'card_confirmed') AND e.promotion_id=?
                ORDER BY e.event_date""", (pid,)).fetchall()
            upcoming_events = [{
                "event_id": r[0],
                "event_date": r[1],
                "event_name": r[2] or "",
                "status": r[3],
                "fight_count": r[4],
                "is_confirmed": r[3] == 'card_confirmed' or r[4] > 0,
            } for r in upcoming_rows]

            # 8. Roster + champ counts
            roster_count = conn.execute(
                "SELECT COUNT(*) FROM fighters WHERE current_promotion_id=? AND is_active=1",
                (pid,)).fetchone()[0]
            champ_count = len(champions)
            total_wcs = conn.execute(
                "SELECT COUNT(DISTINCT weight_class_id) FROM weight_classes").fetchone()[0] or 8

            # 8b. Phase 5 Task 2 — cash_history + yesterday_cash for the
            # SVG sparkline + trend arrow on the cash stat tile.
            # We walk the 7 most-recent finance_transactions for this
            # promo FORWARD from oldest to newest, accumulating the
            # amount to derive the running balance AFTER each
            # transaction. The starting balance (before the oldest of
            # the 7) is `current_cash - sum(amounts)`, returned as
            # `yesterday_cash` for the trend arrow delta.
            #
            # If fewer than 7 transactions exist (new promo), we pad
            # forward with the current cash so the sparkline still
            # renders 7 points (a flat line, no trend). If no
            # transactions at all, cash_history = [cash]*7.
            tx_rows = conn.execute("""SELECT transaction_id, amount
                FROM finance_transactions WHERE promotion_id=?
                ORDER BY transaction_id DESC LIMIT 7""", (pid,)).fetchall()
            # tx_rows is newest-first; we want oldest-first for the walk.
            tx_oldest_first = list(reversed(tx_rows))
            sum_amounts = sum(float(tr[1] or 0) for tr in tx_oldest_first)
            starting_balance = cash - sum_amounts  # balance before oldest tx
            cash_history = []
            running = starting_balance
            for tr in tx_oldest_first:
                running += float(tr[1] or 0)
                cash_history.append(round(running, 2))
            # Pad to 7 points if fewer than 7 transactions (pad at the
            # front with the starting balance so the sparkline trends
            # up to the current cash).
            while len(cash_history) < 7:
                cash_history.insert(0, round(starting_balance, 2))
            yesterday_cash = round(starting_balance, 2)

            # 9. Phase 5 Task 2 — "What Changed" section data.
            # Three streams of recent activity: finance_transactions,
            # fighter_signing news_items (this promo), and active
            # injuries (this promo's fighters). Each capped to 7/5/5
            # rows. The JS layer composes them into a single section.
            recent_tx_rows = conn.execute("""SELECT transaction_date, transaction_type,
                amount, description FROM finance_transactions
                WHERE promotion_id=?
                ORDER BY transaction_id DESC LIMIT 7""", (pid,)).fetchall()
            recent_transactions = [{
                "date": r[0] or "",
                "type": r[1] or "transaction",
                "amount": float(r[2] or 0),
                "description": r[3] or "",
            } for r in recent_tx_rows]

            signing_rows = conn.execute("""SELECT headline, published_at, fighter_id
                FROM news_items
                WHERE promotion_id=? AND topic='fighter_signing'
                ORDER BY published_at DESC LIMIT 5""", (pid,)).fetchall()
            recent_signings = [{
                "headline": r[0] or "",
                "published_at": r[1] or "",
                "fighter_id": r[2],
            } for r in signing_rows]

            injury_rows = conn.execute("""SELECT f.first_name, f.last_name,
                i.injury_type, i.start_date, i.projected_return_date
                FROM injuries i
                JOIN fighters f ON f.fighter_id=i.fighter_id
                WHERE i.is_active=1 AND f.current_promotion_id=?
                ORDER BY i.start_date DESC LIMIT 5""", (pid,)).fetchall()
            recent_injuries = [{
                "fighter_name": f"{r[0]} {r[1]}",
                "injury_type": r[2] or "undisclosed",
                "start_date": r[3] or "",
                "projected_return_date": r[4] or "",
            } for r in injury_rows]

            # 10. Phase 5 Task 2 — "Threats" section.
            # Composite scan of risk surfaces, sorted by severity.
            # Each threat is a {kind, severity, message, fighter_id?} dict.
            # Severity is 'high' (action needed now), 'medium' (this week),
            # or 'low' (heads-up).
            threats = []

            # 10a. Injured champions (highest-severity threat — your
            # title picture is in flux).
            champ_ids_set = {c["fighter_id"] for c in champions}
            if champ_ids_set:
                ph = ",".join(["?"] * len(champ_ids_set))
                inj_champ_rows = conn.execute(
                    "SELECT fighter_id, injury_type, start_date, "
                    "projected_return_date FROM injuries "
                    "WHERE is_active=1 AND fighter_id IN (" + ph + ")",
                    list(champ_ids_set)).fetchall()
                champ_name_map = {c["fighter_id"]: c["name"] for c in champions}
                champ_wc_map = {c["fighter_id"]: c["weight_class"] for c in champions}
                for r in inj_champ_rows:
                    fid = r[0]
                    cname = champ_name_map.get(fid, "your champion")
                    wc = champ_wc_map.get(fid, "title")
                    threats.append({
                        "kind": "injured_champion",
                        "severity": "high",
                        "message": f"{cname} ({wc}) is out with {r[1] or 'an injury'} — expected back {r[3] or 'soon'}.",
                        "fighter_id": fid,
                    })

            # 10b. Expiring contracts (next 30 sim days).
            expiry_rows = conn.execute("""SELECT c.end_date, c.salary,
                fc.fighter_id, f.first_name, f.last_name
                FROM contracts c
                JOIN fighter_contracts fc ON fc.contract_id=c.contract_id
                JOIN fighters f ON f.fighter_id=fc.fighter_id
                WHERE c.status='active' AND f.current_promotion_id=?
                  AND c.end_date >= ? AND c.end_date <= date(?, '+30 days')
                ORDER BY c.end_date LIMIT 5""", (pid, sim_date, sim_date)).fetchall()
            for r in expiry_rows:
                threats.append({
                    "kind": "expiring_contract",
                    "severity": "medium",
                    "message": f"{r[3]} {r[4]}'s contract expires {r[0]}.",
                    "fighter_id": r[2],
                })

            # 10c. Low cash warning (cash < $500K = high, < $2M = medium).
            if cash < 500_000:
                threats.append({
                    "kind": "low_cash",
                    "severity": "high",
                    "message": f"War chest is down to ${cash:,.0f}. Cancel a card or sign cheaper talent.",
                })
            elif cash < 2_000_000:
                threats.append({
                    "kind": "low_cash",
                    "severity": "medium",
                    "message": f"War chest is at ${cash:,.0f}. Watch your spending.",
                })

            # 10d. Low fan trust / reputation.
            if fan_trust < 30:
                threats.append({
                    "kind": "low_fan_trust",
                    "severity": "high" if fan_trust < 15 else "medium",
                    "message": f"Fan trust is at {fan_trust}%. The fans are restless — book a crowd-pleaser.",
                })
            if rep < 30:
                threats.append({
                    "kind": "low_reputation",
                    "severity": "high" if rep < 15 else "medium",
                    "message": f"Your promotion's standing is at {rep}%. You need a marquee moment.",
                })

            # 11. Phase 5 Task 2 — "Opportunities" section.
            # Composite scan of upside surfaces.
            opportunities = []

            # 11a. High-heat rivalries involving a promo fighter.
            heat_rows = conn.execute("""SELECT r.rivalry_heat, r.rivalry_type,
                r.fighter_a_id, r.fighter_b_id,
                fa.first_name, fa.last_name,
                fb.first_name, fb.last_name
                FROM rivalries r
                JOIN fighters fa ON fa.fighter_id=r.fighter_a_id
                JOIN fighters fb ON fb.fighter_id=r.fighter_b_id
                WHERE r.is_active=1 AND r.rivalry_heat >= 60
                  AND (fa.current_promotion_id=? OR fb.current_promotion_id=?)
                ORDER BY r.rivalry_heat DESC LIMIT 3""",
                (pid, pid)).fetchall()
            for r in heat_rows:
                opportunities.append({
                    "kind": "high_heat_rivalry",
                    "severity": "high" if r[0] >= 75 else "medium",
                    "message": f"{r[4]} {r[5]} vs {r[6]} {r[7]} — heat at {r[0]}%. Book the rematch.",
                    "fighter_id": r[2] if r[2] else r[3],
                })

            # 11b. Vacant titles on this promo (free belts to capture).
            vacant_rows = conn.execute("""SELECT wc.name
                FROM titles t
                JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id
                WHERE t.promotion_id=? AND t.is_vacant=1
                ORDER BY COALESCE(wc.display_order, wc.weight_class_id) LIMIT 5""",
                (pid,)).fetchall()
            for r in vacant_rows:
                opportunities.append({
                    "kind": "vacant_title",
                    "severity": "medium",
                    "message": f"The {r[0]} title is vacant. Crown a champion.",
                })

            # 11c. Top free agent targets (top 3 by record wins — voice
            # only, no raw attribute numbers).
            fa_rows = conn.execute("""SELECT f.fighter_id, f.first_name, f.last_name,
                fc.record_wins, fc.record_losses, fc.record_draws, wc.name
                FROM fighters f
                LEFT JOIN fighter_career fc ON fc.fighter_id=f.fighter_id
                LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id
                WHERE f.is_active=1 AND f.current_promotion_id IS NULL
                ORDER BY COALESCE(fc.record_wins, 0) DESC, f.fighter_id
                LIMIT 3""").fetchall()
            for r in fa_rows:
                w = r[3] or 0; l = r[4] or 0; d = r[5] or 0
                opportunities.append({
                    "kind": "free_agent_target",
                    "severity": "low",
                    "message": f"{r[1]} {r[2]} ({r[6] or '—'}) is a free agent with a {w}-{l}-{d} record.",
                    "fighter_id": r[0],
                })

            # 12. Phase 5 Task 2 — "World Stories" section.
            # Top 5 most-recent news items from RIVAL promos (promo_id
            # != player's pid), with the rival promo name resolved.
            world_rows = conn.execute("""SELECT n.headline, n.topic, n.published_at,
                n.fighter_id, p.name AS promo_name
                FROM news_items n
                JOIN promotions p ON p.promotion_id=n.promotion_id
                WHERE n.promotion_id IS NOT NULL AND n.promotion_id != ?
                ORDER BY n.published_at DESC LIMIT 5""", (pid,)).fetchall()
            world_stories = [{
                "headline": r[0] or "",
                "topic": r[1] or "wire",
                "published_at": r[2] or "",
                "fighter_id": r[3],
                "promo_name": r[4] or "",
            } for r in world_rows]

            # Logo (base64 embed for offline use)
            logo_b64 = _load_logo_b64(pid)

            return {
                "promo_id": pid,
                "promo_name": promo_name,
                "promo_logo_b64": logo_b64,
                "sim_date": sim_date,
                "month_name": month_name,
                "year": year,
                "cash": cash,
                # Phase 5 Task 2 — sparkline + trend arrow data
                "cash_history": cash_history,
                "yesterday_cash": yesterday_cash,
                # Phase 7 / Task A1 — raw 0-100 reputation/fan_trust
                # ints DROPPED from the JSON payload (per §17.4 "Rich
                # Not Thin"). The JS bar fill uses the banded tier pct
                # (_reputation_pct / _fan_trust_pct — 100/75/60/35/20
                # for rep, 100/65/40/25 for trust); text display uses
                # the voice phrase. No exact int leaks across the
                # API boundary.
                "reputation_pct": _reputation_pct(rep),
                "reputation_phrase": _reputation_phrase(rep),
                "fan_trust_pct": _fan_trust_pct(fan_trust),
                "fan_trust_phrase": _fan_trust_phrase(fan_trust),
                "size_tier": size_tier,
                "broadcast_tier": broadcast,
                "roster_count": roster_count,
                "champ_count": champ_count,
                "total_wcs": total_wcs,
                "top_story": top_story,
                "echoes": echoes,
                # Phase M3.2 — bidding alerts (rival AI signing intents
                # the player can counter-offer against). Pulled from
                # the same get_bidding_alerts API used by the dedicated
                # bidding war section in the dashboard.
                "bidding_alerts": self.get_bidding_alerts().get("alerts", []),
                "next_event": next_event,
                "upcoming_events": upcoming_events,
                "fighter_watch": watch,
                "champions": champions,
                "recent_results": recent_results,
                "recent_news": recent_news,
                # Phase 5 Task 2 — new sections (What Changed, Threats,
                # Opportunities, World Stories). All additive — no
                # existing fields renamed or removed.
                "recent_transactions": recent_transactions,
                "recent_signings": recent_signings,
                "recent_injuries": recent_injuries,
                "threats": threats,
                "opportunities": opportunities,
                "world_stories": world_stories,
            }
        except Exception as e:
            print(f"[api.get_dashboard_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    # ============================================================
    # ADVANCE DAY (the dopamine button)
    # ============================================================

    def advance_day(self):
        """Advance the simulation by one day.

        Calls services.clock.advance_day(conn) which delegates to
        tick_processor.run_tick(conn). run_tick handles:
          - Updating simulation_clock
          - _check_retirements, _check_training_camps,
            _check_injury_recovery, _check_contract_expiry
          - Publishing Events.TICK_ADVANCED on the event bus
          - conn.commit()

        Returns the new clock dict (so JS can update the top bar).
        """
        try:
            advance_day(self.conn)
            self.conn.commit()
            return self.get_clock()
        except Exception as e:
            print(f"[api.advance_day] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    def advance_days(self, n):
        """Phase F2.2 — advance the simulation by N days in one call.

        Used by the "Sim Week" button (n=7) + could be used by future
        "Sim Month" / "Sim to Date" features. Calls run_tick(conn,
        'day', n) which loops N times in C-speed Python (no JS round-
        trip per day — the entire 7-day sim runs in one Python call,
        typically <500ms even on a 4000-fighter world DB).

        Returns {ok, days_advanced, new_date, clock} so the JS layer
        can update the top bar + tell the overlay to hide.

        Args:
          n: int — number of days to advance (clamped to [1, 90] to
             prevent runaway ticks. 90 days = ~3 sim-months which is
             the longest reasonable "skip ahead" the player would
             want; longer skips should use advance_to_next_event
             which advances to a specific scheduled date).
        """
        try:
            n_int = max(1, min(90, int(n or 1)))
            from tick_processor import run_tick
            run_tick(self.conn, 'day', n_int)
            self.conn.commit()
            clock = self.get_clock()
            return {
                "ok": True,
                "days_advanced": n_int,
                "new_date": clock.get("current_date") if clock else None,
                "clock": clock,
            }
        except Exception as e:
            print(f"[api.advance_days] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def advance_to_next_event(self):
        """Phase F2.2 — advance the simulation to the next scheduled
        event for the player's promotion.

        Used by the "Skip to Show" button. Finds the next event on
        the player's promo with status='scheduled' or 'card_confirmed'
        (the only states where the event hasn't run yet) whose event_
        date > current sim date. Computes the day delta, runs that
        many ticks via run_tick(conn, 'day', n), returns the result
        so the JS layer can hide the overlay + navigate to the
        Fight Night screen if applicable.

        Returns:
          {ok, days_advanced, new_date, event_id, event_date, clock}
          on success.
          {ok: True, days_advanced: 0, message: 'no scheduled events'}
          if the player has no upcoming events (the overlay hides
          with a toast instead of running any ticks).
          {ok: False, error: str} on exception.
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False,
                        "error": "No player promotion selected."}
            # Read current sim date.
            clock = self.get_clock()
            if not clock:
                return {"ok": False, "error": "Could not read sim clock."}
            current_date = clock.get("current_date")
            if not current_date:
                return {"ok": False, "error": "Sim clock has no current_date."}
            # Find the next scheduled event for this promo (status
            # 'scheduled' or 'card_confirmed' — those are the events
            # that haven't run yet). 'completed' events are in the
            # past and irrelevant.
            row = self.conn.execute(
                "SELECT event_id, event_date FROM events "
                "WHERE promotion_id=? "
                "  AND status IN ('scheduled', 'card_confirmed') "
                "  AND event_date > ? "
                "ORDER BY event_date ASC LIMIT 1",
                (pid, current_date),
            ).fetchone()
            if not row:
                return {
                    "ok": True,
                    "days_advanced": 0,
                    "new_date": current_date,
                    "clock": clock,
                    "message": "No scheduled events on the horizon. "
                               "Stack a card to give the fans something "
                               "to remember.",
                }
            event_id, event_date = row
            # Compute day delta. event_date is YYYY-MM-DD.
            from datetime import datetime as _dt
            try:
                cur_dt = _dt.strptime(str(current_date)[:10], "%Y-%m-%d")
                evt_dt = _dt.strptime(str(event_date)[:10], "%Y-%m-%d")
                delta_days = (evt_dt - cur_dt).days
            except (ValueError, TypeError):
                return {"ok": False,
                        "error": f"Date parse failed: cur={current_date} "
                                 f"evt={event_date}"}
            if delta_days <= 0:
                # Event is today or in the past — no ticks needed,
                # but still return the event_id so the JS layer can
                # navigate to Fight Night if it's today.
                return {
                    "ok": True,
                    "days_advanced": 0,
                    "new_date": current_date,
                    "event_id": event_id,
                    "event_date": event_date,
                    "clock": clock,
                    "message": "Your event is today — head to Fight Night.",
                }
            # Cap at 365 days (defensive — a corrupt event_date 10
            # years out shouldn't hang the sim for 3650 ticks). 365
            # is the longest reasonable skip; anything further is
            # likely a data issue worth flagging.
            delta_days = min(delta_days, 365)
            from tick_processor import run_tick
            run_tick(self.conn, 'day', delta_days)
            self.conn.commit()
            new_clock = self.get_clock()
            return {
                "ok": True,
                "days_advanced": delta_days,
                "new_date": new_clock.get("current_date") if new_clock else None,
                "event_id": event_id,
                "event_date": event_date,
                "clock": new_clock,
            }
        except Exception as e:
            print(f"[api.advance_to_next_event] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_random_fighter_id(self):
        """Phase F2.2 — return a random fighter_id from the player's
        promotion roster. Used by the processing overlay to cycle
        through fighter profile snapshots during Sim Week / Skip to
        Show (visual feedback that the sim is doing something).

        Returns a fighter_id (int) on the player's promo, or None if
        the roster is empty. The JS layer calls this in a setInterval
        every ~3s and then calls get_fighter_profile_data to fetch
        the snapshot — keeping the Python side stateless (no need
        to track "which fighters have been shown").
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"fighter_id": None}
            row = self.conn.execute(
                "SELECT fighter_id FROM fighters "
                "WHERE current_promotion_id=? AND is_active=1 "
                "ORDER BY RANDOM() LIMIT 1",
                (pid,),
            ).fetchone()
            return {"fighter_id": row[0] if row else None}
        except Exception as e:
            print(f"[api.get_random_fighter_id] {e}", flush=True)
            return {"fighter_id": None}

    # ============================================================
    # ROSTER / FIGHTERS — full implementation
    # ============================================================

    def get_roster_data(self, promo_id, page=1, filters=None):
        """Return paginated roster data for `promo_id`.

        Per SCREEN_DATA_AUDIT §2.2 + GUI_PLAN §6.2:
          - 9 columns: Active dot | Name (link) | Age (mono) | WC (mono)
            | Stage (SHORT italic) | Form (SHORT italic) | Record (mono)
            | Gym (text) | Nat (3-letter).
          - Paginated at SQL level: LIMIT 20 OFFSET ?.
          - Filters: wc (weight_class_id), gender, stage (career_phase
            label), search (LIKE first/last/nickname).
          - Sort: by column name (name, age, wc, record_wins,
            record_losses), asc/desc.
          - NEVER reads fighter_attributes / fighter_personality. All
            voice phrases come from fighter_descriptors.

        Returns: {
            promo_id, page, per_page, total, total_pages,
            fighters: [ { fighter_id, name, nickname, age, wc_name,
                          stage_short, form_short, record_str, gym_name,
                          nat_code, momentum_label, is_injured,
                          is_suspended, is_champion } ... ],
            weight_classes: [ { id, name, count } ... ],
            filters_applied: {...}
        }
        """
        try:
            pid = int(promo_id)
            page = max(1, int(page))
            filters = filters or {}
            per_page = 20
            offset = (page - 1) * per_page
            conn = self.conn

            # Sim date for age computation
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None

            # ----- Build WHERE clause from filters -----
            where = ["f.current_promotion_id = ?", "f.is_active = 1"]
            params = [pid]
            wc_filter = filters.get("wc")
            if wc_filter and str(wc_filter) != "0" and str(wc_filter) != "":
                where.append("f.weight_class_id = ?")
                params.append(int(wc_filter))
            gender = filters.get("gender")
            if gender and gender != "all":
                where.append("f.gender = ?")
                params.append(gender)
            stage = filters.get("stage")
            if stage and stage != "all":
                # stage filter matches the LABEL of career_phase_short
                where.append("fd.career_phase_short LIKE ? OR fd.career_phase LIKE ?")
                params.append(stage + "||%")
                params.append(stage + "||%")
            search = (filters.get("search") or "").strip()
            if search:
                where.append("(f.first_name LIKE ? OR f.last_name LIKE ? OR f.nickname LIKE ? "
                             "OR (f.first_name || ' ' || f.last_name) LIKE ?)")
                like = "%" + search + "%"
                params.extend([like, like, like, like])

            where_sql = " AND ".join(where)

            # ----- Sorting -----
            sort_col = (filters.get("sort_col") or "name").lower()
            sort_dir = (filters.get("sort_dir") or "asc").lower()
            sort_map = {
                "name": "f.last_name, f.first_name",
                "age": "f.date_of_birth",
                "wc": "wc_name",
                "stage": "fd.career_phase_short",
                "form": "fd.momentum_short",
                "record": "fc.record_wins",
                "wins": "fc.record_wins",
                "losses": "fc.record_losses",
                "gym": "gym_name",
            }
            sort_expr = sort_map.get(sort_col, "f.last_name, f.first_name")
            sort_dir_sql = "DESC" if sort_dir == "desc" else "ASC"
            # ASC for last_name + first_name needs no direction on second
            if sort_col == "name":
                sort_expr = "f.last_name " + sort_dir_sql + ", f.first_name " + sort_dir_sql
            else:
                sort_expr = sort_expr + " " + sort_dir_sql

            # ----- Total count -----
            count_sql = (
                "SELECT COUNT(*) FROM fighters f "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
                "WHERE " + where_sql
            )
            total = conn.execute(count_sql, params).fetchone()[0]
            total_pages = max(1, (total + per_page - 1) // per_page)

            # ----- Champion fighter_ids for this promo (gold active dot) -----
            champ_ids = set()
            for r in conn.execute(
                "SELECT current_champion_fighter_id FROM titles "
                "WHERE promotion_id=? AND is_vacant=0 AND current_champion_fighter_id IS NOT NULL",
                (pid,),
            ).fetchall():
                champ_ids.add(r[0])

            # ----- Phase 5 Task 3: currently-watched fighter_ids -----
            # One batched query for the whole promo (avoids N+1). The
            # ★ column on the roster table reads `is_watched` per row.
            # Note: the roster screen is the PLAYER's promo by spec, so
            # the watchlist here is always the player's own watchlist.
            watched_id_set = set(
                fid for (fid, _since)
                in self._watched_fighter_ids_for_promo(pid)
            )

            # ----- Main query — 20 rows -----
            # Phase 6 / Task C1 — replaced the two correlated
            # subqueries for injury_count + susp_count with LEFT
            # JOINs to injuries + suspensions (filtered to is_active=1)
            # and COUNT(DISTINCT ...) over GROUP BY f.fighter_id. The
            # correlated-subquery pattern ran 2 subqueries per row →
            # 40 subqueries for a 20-row page. The JOIN+GROUP BY
            # pattern computes both counts in a single query.
            #
            # Important: the LEFT JOIN conditions put the `is_active=1`
            # filter in the JOIN clause (not the WHERE clause) so that
            # fighters with no active injuries/suspensions still appear
            # in the result set (COUNT(*) returns 0 for them). Putting
            # `i.is_active=1` in WHERE would convert the LEFT JOIN to
            # an effective INNER JOIN and drop fighters with no
            # matching injuries.
            rows = conn.execute(
                "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
                "f.date_of_birth, f.weight_class_id, "
                "wc.name AS wc_name, "
                "fd.career_phase_short, fd.momentum_short, fd.career_phase, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "g.name AS gym_name, "
                "n.name AS nation_name, n.nation_id, "
                "COUNT(DISTINCT i.injury_id) AS injury_count, "
                "COUNT(DISTINCT s.suspension_id) AS susp_count "
                "FROM fighters f "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
                "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
                "LEFT JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id "
                "LEFT JOIN gyms g ON g.gym_id = f.current_gym_id "
                "LEFT JOIN nations n ON n.nation_id = f.birth_nation_id "
                "LEFT JOIN injuries i ON i.fighter_id = f.fighter_id "
                "  AND i.is_active = 1 "
                "LEFT JOIN suspensions s ON s.fighter_id = f.fighter_id "
                "  AND s.is_active = 1 "
                "WHERE " + where_sql + " "
                "GROUP BY f.fighter_id "
                "ORDER BY " + sort_expr + ", f.fighter_id ASC "
                "LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            fighters = []
            for r in rows:
                fid = r[0]
                age = _compute_age(r[4], sim_date)
                stage_short = _decode_phrase(r[7])
                form_short = _decode_phrase(r[8])
                momentum_label = _decode_label(r[8]) if r[8] else ""
                record_str = f"{r[10] or 0}-{r[11] or 0}-{r[12] or 0}"
                fighters.append({
                    "fighter_id": fid,
                    "name": f"{r[1]} {r[2]}",
                    "nickname": r[3] or "",
                    "age": age,
                    "weight_class_id": r[5],
                    "wc_name": (r[6] or "").upper(),
                    "stage_short": stage_short,
                    "form_short": form_short,
                    "momentum_label": momentum_label,
                    "record_str": record_str,
                    "record_wins": r[10] or 0,
                    "record_losses": r[11] or 0,
                    "record_draws": r[12] or 0,
                    "gym_name": r[13] or "—",
                    "nat_code": _nation_iso3(r[14], r[15]),
                    "is_injured": (r[16] or 0) > 0,
                    "is_suspended": (r[17] or 0) > 0,
                    "is_champion": fid in champ_ids,
                    # Phase 5 Task 3 — drives the ★ column state.
                    "is_watched": fid in watched_id_set,
                })

            # ----- Weight class distribution viz -----
            wc_rows = conn.execute(
                "SELECT wc.weight_class_id, wc.name, wc.gender, COUNT(*) AS cnt, wc.display_order "
                "FROM fighters f "
                "JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id "
                "WHERE f.current_promotion_id=? AND f.is_active=1 "
                "GROUP BY wc.weight_class_id "
                "ORDER BY wc.gender, COALESCE(wc.display_order, wc.weight_class_id)",
                (pid,),
            ).fetchall()
            weight_classes = [{
                "id": w[0], "name": w[1], "gender": w[2], "count": w[3]
            } for w in wc_rows]

            # CR-7: promo name + logo for the roster section header.
            # Same pattern as get_dashboard_data (line ~769-774).
            promo_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?", (pid,)
            ).fetchone()
            promo_name = promo_row[0] if promo_row else f"Promotion {pid}"
            promo_logo_b64 = _load_logo_b64(pid)

            return {
                "promo_id": pid,
                "promo_name": promo_name,
                "promo_logo_b64": promo_logo_b64,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "fighters": fighters,
                "weight_classes": weight_classes,
                "filters_applied": filters,
            }
        except Exception as e:
            print(f"[api.get_roster_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    def get_free_agents(self, page=1, filters=None):
        """Return paginated free-agent data.

        Per SCREEN_DATA_AUDIT §3.2 + GUI_PLAN §6.4:
          - 8 columns: Name (link) | Age | WC | Stage (SHORT italic)
            | Ceiling (voice phrase or "????") | Form (SHORT italic)
            | Record (mono) | Gym.
          - Paginated at SQL level: LIMIT 20 OFFSET ?.
          - Filters: wc, ceiling, search.
          - Ceiling is derived from fighter_career.potential ONLY IF
            the fighter has a scouting_report — otherwise "????".
          - NEVER returns raw potential. Only the voice phrase or
            the literal "????" string.

        Returns: {
            page, per_page, total, total_pages,
            fighters: [...],
            filters_applied: {...}
        }
        """
        try:
            page = max(1, int(page))
            filters = filters or {}
            per_page = 20
            offset = (page - 1) * per_page
            conn = self.conn

            clock = get_clock(conn)
            sim_date = clock[0] if clock else None

            where = ["f.current_promotion_id IS NULL", "f.is_active = 1", "f.is_retired = 0"]
            params = []
            wc_filter = filters.get("wc")
            if wc_filter and str(wc_filter) != "0" and str(wc_filter) != "":
                where.append("f.weight_class_id = ?")
                params.append(int(wc_filter))
            ceiling_filter = filters.get("ceiling")
            if ceiling_filter and ceiling_filter != "all" and ceiling_filter != "unknown":
                # Filter by potential bucket — derived server-side
                buckets = _ceiling_potential_ranges(ceiling_filter)
                if buckets:
                    where.append("(fc.potential BETWEEN ? AND ?)")
                    params.extend(buckets)
            elif ceiling_filter == "unknown":
                # Unknown = no scouting report
                where.append("sr.scouting_report_id IS NULL")
            search = (filters.get("search") or "").strip()
            if search:
                where.append("(f.first_name LIKE ? OR f.last_name LIKE ? OR f.nickname LIKE ? "
                             "OR (f.first_name || ' ' || f.last_name) LIKE ?)")
                like = "%" + search + "%"
                params.extend([like, like, like, like])

            # ----- CR-4 (docs/CR1_4_PLAN.md §4.4): new filters -----
            # gender: All / Men / Women
            gender_filter = (filters.get("gender") or "all").lower()
            if gender_filter in ("male", "female"):
                where.append("f.gender = ?")
                params.append(gender_filter)

            # age_range: All / Prospects (≤25) / Prime (26-32) / Veterans (33+)
            age_range = (filters.get("age_range") or "all").lower()
            if age_range != "all" and sim_date:
                try:
                    sim_dt = datetime.strptime(sim_date[:10], "%Y-%m-%d")

                    def _years_ago(n):
                        """Return sim_dt minus n years (handles Feb 29)."""
                        try:
                            return sim_dt.replace(year=sim_dt.year - n)
                        except ValueError:
                            # Feb 29 in non-leap target year → use Feb 28
                            return sim_dt.replace(year=sim_dt.year - n, day=28)

                    if age_range == "prospect":  # age ≤ 25
                        cutoff = _years_ago(25).strftime("%Y-%m-%d")
                        where.append("f.date_of_birth >= ?")
                        params.append(cutoff)
                    elif age_range == "prime":  # age 26-32
                        lo = _years_ago(32).strftime("%Y-%m-%d")
                        hi = _years_ago(26).strftime("%Y-%m-%d")
                        where.append("f.date_of_birth BETWEEN ? AND ?")
                        params.extend([lo, hi])
                    elif age_range == "veteran":  # age 33+
                        cutoff = _years_ago(33).strftime("%Y-%m-%d")
                        where.append("f.date_of_birth <= ?")
                        params.append(cutoff)
                except Exception:
                    pass

            # nationality: filter by birth_nation_id (top 20 list returned
            # in the payload so the JS dropdown can populate itself).
            nat_filter = filters.get("nationality")
            if nat_filter is not None and str(nat_filter) != "all" and str(nat_filter) != "":
                try:
                    nat_id = int(nat_filter)
                    where.append("f.birth_nation_id = ?")
                    params.append(nat_id)
                except (ValueError, TypeError):
                    pass

            where_sql = " AND ".join(where)

            # Count
            count_sql = (
                "SELECT COUNT(*) FROM fighters f "
                "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
                "LEFT JOIN scouting_reports sr ON sr.target_fighter_id = f.fighter_id "
                "WHERE " + where_sql
            )
            total = conn.execute(count_sql, params).fetchone()[0]
            total_pages = max(1, (total + per_page - 1) // per_page)

            # ----- CR-4: dynamic ORDER BY (SQL doesn't allow ? for cols) -----
            # sort_col whitelist: name / age / wc / ceiling / record.
            # For 'ceiling': unscouted rows (sr.scouting_report_id IS NULL)
            # ALWAYS sort last regardless of direction — prevents the
            # player from inferring "????" fighters' true ceiling by
            # sorting ascending vs descending (scouting safety rule,
            # docs/CR1_4_PLAN.md §4.2).
            sort_col = (filters.get("sort_col") or "ceiling").lower()
            sort_dir = (filters.get("sort_dir") or "desc").lower()
            if sort_dir not in ("asc", "desc"):
                sort_dir = "desc"
            # Whitelist sort_col — never inject user input into SQL raw.
            if sort_col == "name":
                order_by = (f"f.last_name {sort_dir}, f.first_name {sort_dir}, "
                            f"f.fighter_id ASC")
            elif sort_col == "age":
                # Younger fighter = later DOB. age ASC (youngest first)
                # → DOB DESC. age DESC (oldest first) → DOB ASC.
                dob_dir = "DESC" if sort_dir == "asc" else "ASC"
                order_by = f"f.date_of_birth {dob_dir}, f.fighter_id ASC"
            elif sort_col == "wc":
                order_by = f"wc.name {sort_dir}, f.fighter_id ASC"
            elif sort_col == "record":
                # Win percentage: wins / (wins + losses + draws).
                # Avoid div-by-zero with CASE WHEN guard.
                order_by = (
                    "CASE WHEN COALESCE(fc.record_wins,0) + "
                    "COALESCE(fc.record_losses,0) + "
                    "COALESCE(fc.record_draws,0) > 0 "
                    "THEN COALESCE(fc.record_wins,0) * 1.0 / "
                    "(COALESCE(fc.record_wins,0) + "
                    "COALESCE(fc.record_losses,0) + "
                    "COALESCE(fc.record_draws,0)) "
                    "ELSE 0 END "
                    f"{sort_dir}, f.fighter_id ASC"
                )
            elif sort_col == "ceiling":
                # Scouting safety: unscouted LAST always (primary key).
                # Secondary sort: fc.potential (1:1 with tier for
                # scouted fighters). Tertiary: fighter_id for stable
                # tie-break.
                order_by = (
                    "CASE WHEN sr.scouting_report_id IS NULL THEN 1 ELSE 0 END ASC, "
                    f"fc.potential {sort_dir}, f.fighter_id ASC"
                )
            else:
                # Default / unknown sort_col: same as 'ceiling' DESC.
                order_by = (
                    "CASE WHEN sr.scouting_report_id IS NULL THEN 1 ELSE 0 END ASC, "
                    "fc.potential DESC, f.fighter_id ASC"
                )

            rows = conn.execute(
                "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
                "f.date_of_birth, f.weight_class_id, f.gender, "
                "wc.name AS wc_name, "
                "fd.career_phase_short, fd.momentum_short, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "fc.potential, "
                "sr.scouting_report_id, sr.estimated_ceiling, "
                "g.name AS gym_name, "
                "n.name AS nation_name, n.nation_id "
                "FROM fighters f "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
                "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
                "LEFT JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id "
                "LEFT JOIN gyms g ON g.gym_id = f.current_gym_id "
                "LEFT JOIN nations n ON n.nation_id = f.birth_nation_id "
                "LEFT JOIN scouting_reports sr ON sr.target_fighter_id = f.fighter_id "
                "WHERE " + where_sql + " "
                "ORDER BY " + order_by + " "
                "LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            fighters = []
            for r in rows:
                fid = r[0]
                age = _compute_age(r[4], sim_date)
                # NOTE: column indices shifted by 1 vs the old SELECT
                # because we added f.gender at index 6.
                # 0=fighter_id, 1=first_name, 2=last_name, 3=nickname,
                # 4=dob, 5=wc_id, 6=gender, 7=wc_name,
                # 8=stage_short, 9=momentum_short,
                # 10-12=record_wins/losses/draws, 13=potential,
                # 14=scouting_report_id, 15=estimated_ceiling,
                # 16=gym_name, 17=nation_name, 18=nation_id.
                if r[14]:  # scouting_report_id present
                    ceiling_display = r[15] or _ceiling_phrase_from_potential(r[13])
                    ceiling_scouted = True
                else:
                    ceiling_display = "????"
                    ceiling_scouted = False
                fighters.append({
                    "fighter_id": fid,
                    "name": f"{r[1]} {r[2]}",
                    "nickname": r[3] or "",
                    "age": age,
                    "gender": r[6] or "",
                    "weight_class_id": r[5],
                    "wc_name": (r[7] or "").upper(),
                    "stage_short": _decode_phrase(r[8]),
                    "form_short": _decode_phrase(r[9]),
                    "record_str": f"{r[10] or 0}-{r[11] or 0}-{r[12] or 0}",
                    "ceiling_display": ceiling_display,
                    "ceiling_scouted": ceiling_scouted,
                    "gym_name": r[16] or "—",
                    "nat_code": _nation_iso3(r[17], r[18]),
                })

            # ----- CR-3a (docs/CR1_4_PLAN.md §3.2): weight_classes -
            # with `gender` field for Men's/Women's optgroup dropdown.
            wc_rows = conn.execute(
                "SELECT wc.weight_class_id, wc.name, wc.gender, "
                "COUNT(*) AS cnt, wc.display_order "
                "FROM fighters f "
                "JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id "
                "WHERE f.current_promotion_id IS NULL "
                "  AND f.is_active = 1 AND f.is_retired = 0 "
                "GROUP BY wc.weight_class_id "
                "ORDER BY wc.gender, "
                "COALESCE(wc.display_order, wc.weight_class_id)",
            ).fetchall()
            weight_classes = [{
                "id": w[0], "name": w[1], "gender": w[2], "count": w[3]
            } for w in wc_rows]

            # ----- CR-4: top 20 nationalities by FA count (for the -
            # nationality filter dropdown). Format: [{id, name, count}].
            nat_rows = conn.execute(
                "SELECT n.nation_id, n.name, COUNT(*) AS cnt "
                "FROM fighters f "
                "JOIN nations n ON n.nation_id = f.birth_nation_id "
                "WHERE f.current_promotion_id IS NULL "
                "  AND f.is_active = 1 AND f.is_retired = 0 "
                "GROUP BY n.nation_id "
                "ORDER BY cnt DESC, n.name ASC LIMIT 20",
            ).fetchall()
            nationalities = [{
                "id": n[0], "name": n[1], "count": n[2]
            } for n in nat_rows]

            return {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "fighters": fighters,
                "weight_classes": weight_classes,
                "nationalities": nationalities,
                "filters_applied": filters,
            }
        except Exception as e:
            print(f"[api.get_free_agents] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    # ============================================================
    # CR-9 — RIVAL PROMOTIONS ("The Competition" screen)
    # Read-only views of OTHER promotions (not the player's own).
    # No sign/cut/book actions — those are player-only.
    # ============================================================

    def get_rival_promotions(self):
        """Return list of rival promotions (excluding the player's own).

        Per CR-9 (docs/CR5_9_PLAN.md §5): lets the player see what
        other promos look like — roster size, champion count,
        reputation phrase, fan trust phrase. Read-only.

        Phase 6 / Task B8 — LEFT JOINs `promotion_descriptors` (the
        cache table populated by Task A2's promotion_engine; 10 rows).
        The raw `reputation` / `fan_trust` / `current_cash` ints are
        KEPT in the response for bar-fill widths (§17.4 carve-out),
        but the JS layer should display the voice phrases
        (`prestige_desc`, `market_position_desc`, `roster_quality_desc`)
        instead of the raw ints.

        Returns: [
            { promotion_id, name, size_tier, broadcast_tier,
              reputation, reputation_phrase, fan_trust,
              fan_trust_phrase, current_cash, roster_count,
              champ_count, logo_b64,
              prestige_desc, market_position_desc, roster_quality_desc }
        ]
        """
        try:
            pid = self.get_player_promotion()
            rows = self.conn.execute("""
                SELECT p.promotion_id, p.name, p.size_tier, p.broadcast_tier,
                       p.reputation, p.fan_trust, p.current_cash,
                       (SELECT COUNT(*) FROM fighters f
                          WHERE f.current_promotion_id=p.promotion_id
                            AND f.is_active=1) AS roster_count,
                       (SELECT COUNT(*) FROM titles t
                          WHERE t.promotion_id=p.promotion_id
                            AND t.is_vacant=0) AS champ_count,
                       pd.prestige_desc, pd.market_position_desc,
                       pd.roster_quality_desc
                FROM promotions p
                LEFT JOIN promotion_descriptors pd
                  ON pd.promotion_id = p.promotion_id
                WHERE p.promotion_id != ?
                ORDER BY p.size_tier DESC, p.reputation DESC
            """, (pid,)).fetchall()
            return [{
                "promotion_id": r[0],
                "name": r[1],
                "size_tier": (r[2] or "").upper(),
                "broadcast_tier": (r[3] or "").upper(),
                # Phase 6 / Task B8 — raw ints KEPT in JSON for bar
                # widths (§17.4 carve-out). The JS should NOT display
                # these as text — use the *_desc voice phrases below.
                "reputation": r[4] or 0,
                "reputation_phrase": _reputation_phrase(r[4] or 0),
                "fan_trust": r[5] or 0,
                "fan_trust_phrase": _fan_trust_phrase(r[5] or 0),
                "current_cash": float(r[6] or 0),
                "roster_count": r[7],
                "champ_count": r[8],
                "logo_b64": _load_logo_b64(r[0]),
                # Phase 6 / Task B8 — voice phrases from the
                # promotion_descriptors cache table (§17.1).
                "prestige_desc": r[9] or "",
                "market_position_desc": r[10] or "",
                "roster_quality_desc": r[11] or "",
            } for r in rows]
        except Exception as e:
            print(f"[api.get_rival_promotions] {e}\n{traceback.format_exc()}",
                  flush=True)
            return []

    def get_rival_roster(self, promo_id, page=1, filters=None):
        """Return a rival promotion's roster (read-only).

        Mirrors get_roster_data but for a non-player promo. Same
        filters + pagination + column shape. NO sign/cut/book
        actions — those are player-only.

        Per CR-9 (docs/CR5_9_PLAN.md §5.3): the player can scout
        rival rosters but cannot see potential/ceiling/scouting
        reports for fighters on rival promos (scouting safety).
        Only stage/form voice phrases + record are exposed.

        Returns: {
            promo_id, promo_name, page, per_page, total, total_pages,
            fighters: [ { fighter_id, name, nickname, age,
                          weight_class_id, wc_name, stage_short,
                          form_short, momentum_label, record_str,
                          record_wins, record_losses, record_draws,
                          gym_name, nat_code, gender,
                          is_injured, is_suspended, is_champion } ... ],
            weight_classes: [ { id, name, gender, count } ... ],
            filters_applied: {...}
        }
        """
        try:
            pid = int(promo_id)
            filters = filters or {}
            page = max(1, int(page))
            per_page = 20
            offset = (page - 1) * per_page
            conn = self.conn

            # Sim date for age computation
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None

            # ----- Build WHERE clause (mirrors get_roster_data) -----
            where = ["f.current_promotion_id = ?", "f.is_active = 1"]
            params = [pid]

            wc_filter = filters.get("wc")
            if wc_filter and str(wc_filter) != "0" and str(wc_filter) != "":
                where.append("f.weight_class_id = ?")
                params.append(int(wc_filter))

            gender = filters.get("gender")
            if gender and gender != "all":
                where.append("f.gender = ?")
                params.append(gender)

            stage = filters.get("stage")
            if stage and stage != "all":
                # Match the LABEL prefix of career_phase / career_phase_short
                where.append("(fd.career_phase_short LIKE ? OR fd.career_phase LIKE ?)")
                params.append(stage + "||%")
                params.append(stage + "||%")

            search = (filters.get("search") or "").strip()
            if search:
                where.append("(f.first_name LIKE ? OR f.last_name LIKE ? "
                             "OR f.nickname LIKE ? "
                             "OR (f.first_name || ' ' || f.last_name) LIKE ?)")
                like = "%" + search + "%"
                params.extend([like, like, like, like])

            where_sql = " AND ".join(where)

            # ----- Sorting (whitelisted — never inject user input raw) -----
            sort_col = (filters.get("sort_col") or "name").lower()
            sort_dir = (filters.get("sort_dir") or "asc").lower()
            if sort_dir not in ("asc", "desc"):
                sort_dir = "asc"
            sort_map = {
                "name": "f.last_name, f.first_name",
                "age": "f.date_of_birth",
                "wc": "wc_name",
                "stage": "fd.career_phase_short",
                "form": "fd.momentum_short",
                "record": "fc.record_wins",
                "wins": "fc.record_wins",
                "losses": "fc.record_losses",
                "gym": "gym_name",
            }
            sort_expr = sort_map.get(sort_col, "f.last_name, f.first_name")
            sort_dir_sql = "DESC" if sort_dir == "desc" else "ASC"
            if sort_col == "name":
                sort_expr = ("f.last_name " + sort_dir_sql +
                             ", f.first_name " + sort_dir_sql)
            else:
                sort_expr = sort_expr + " " + sort_dir_sql

            # ----- Total count -----
            count_sql = (
                "SELECT COUNT(*) FROM fighters f "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
                "WHERE " + where_sql
            )
            total = conn.execute(count_sql, params).fetchone()[0]
            total_pages = max(1, (total + per_page - 1) // per_page)

            # ----- Champion fighter_ids for THIS rival promo (gold dot) -----
            champ_ids = set()
            for r in conn.execute(
                "SELECT current_champion_fighter_id FROM titles "
                "WHERE promotion_id=? AND is_vacant=0 "
                "AND current_champion_fighter_id IS NOT NULL",
                (pid,),
            ).fetchall():
                champ_ids.add(r[0])

            # ----- Main query — 20 rows (same shape as get_roster_data) -----
            rows = conn.execute(
                "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
                "f.date_of_birth, f.weight_class_id, f.gender, "
                "wc.name AS wc_name, "
                "fd.career_phase_short, fd.momentum_short, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "g.name AS gym_name, "
                "n.name AS nation_name, n.nation_id, "
                "(SELECT COUNT(*) FROM injuries i "
                "   WHERE i.fighter_id=f.fighter_id AND i.is_active=1) AS injury_count, "
                "(SELECT COUNT(*) FROM suspensions s "
                "   WHERE s.fighter_id=f.fighter_id AND s.is_active=1) AS susp_count "
                "FROM fighters f "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
                "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
                "LEFT JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id "
                "LEFT JOIN gyms g ON g.gym_id = f.current_gym_id "
                "LEFT JOIN nations n ON n.nation_id = f.birth_nation_id "
                "WHERE " + where_sql + " "
                "ORDER BY " + sort_expr + ", f.fighter_id ASC "
                "LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            fighters = []
            for r in rows:
                fid = r[0]
                age = _compute_age(r[4], sim_date)
                stage_short = _decode_phrase(r[8])
                form_short = _decode_phrase(r[9])
                momentum_label = _decode_label(r[9]) if r[9] else ""
                record_str = f"{r[10] or 0}-{r[11] or 0}-{r[12] or 0}"
                fighters.append({
                    "fighter_id": fid,
                    "name": f"{r[1]} {r[2]}",
                    "nickname": r[3] or "",
                    "age": age,
                    "gender": r[6] or "unknown",
                    "weight_class_id": r[5],
                    "wc_name": (r[7] or "").upper(),
                    "stage_short": stage_short,
                    "form_short": form_short,
                    "momentum_label": momentum_label,
                    "record_str": record_str,
                    "record_wins": r[10] or 0,
                    "record_losses": r[11] or 0,
                    "record_draws": r[12] or 0,
                    "gym_name": r[13] or "—",
                    "nat_code": _nation_iso3(r[14], r[15]),
                    "is_injured": (r[16] or 0) > 0,
                    "is_suspended": (r[17] or 0) > 0,
                    "is_champion": fid in champ_ids,
                })

            # ----- Weight class distribution (mirrors roster payload) -----
            wc_rows = conn.execute(
                "SELECT wc.weight_class_id, wc.name, wc.gender, "
                "COUNT(*) AS cnt, wc.display_order "
                "FROM fighters f "
                "JOIN weight_classes wc ON wc.weight_class_id = f.weight_class_id "
                "WHERE f.current_promotion_id=? AND f.is_active=1 "
                "GROUP BY wc.weight_class_id "
                "ORDER BY wc.gender, COALESCE(wc.display_order, wc.weight_class_id)",
                (pid,),
            ).fetchall()
            weight_classes = [{
                "id": w[0], "name": w[1], "gender": w[2], "count": w[3]
            } for w in wc_rows]

            # ----- Promo name for the roster view header -----
            promo_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?", (pid,)
            ).fetchone()
            promo_name = promo_row[0] if promo_row else f"Promotion {pid}"

            return {
                "promo_id": pid,
                "promo_name": promo_name,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "fighters": fighters,
                "weight_classes": weight_classes,
                "filters_applied": filters,
                # CR-9: read-only flag — JS uses this to hide Sign/Cut/Book.
                "read_only": True,
            }
        except Exception as e:
            print(f"[api.get_rival_roster] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    def get_fighter_profile(self, fighter_id):
        """Backward-compat wrapper — delegates to get_fighter_profile_data."""
        return self.get_fighter_profile_data(fighter_id)

    def get_fighter_decision_history(self, fighter_id):
        """Return the player's decision history for a fighter.

        PHASE-R (Reward Layer §4): public API for the Fighter Profile
        'Your History with [Fighter]' section. Returns a chronological
        list of every sign / cut / book / scout decision the player
        has made about this fighter, oldest-first (timeline order).

        Also computes derived fields (sign_date, record_under_you,
        biggest_win, contract info) — same data the profile payload
        returns under 'your_history'. Exposed as a separate method so
        the JS side can re-fetch just this slice after a Cut / Sign
        action without reloading the full profile.

        Returns dict with: {decisions, sign_date, contract_months,
        contract_salary, contract_expires_in_days, record_under_you,
        biggest_win}. Returns {error: ...} on failure.
        """
        try:
            fid = int(fighter_id)
            conn = self.conn
            player_promo = self.get_player_promotion()
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None

            from player_decisions import (
                get_decisions_for_fighter, TYPE_SIGN,
            )
            decisions = get_decisions_for_fighter(conn, fid)
            decisions = [d for d in decisions
                         if (d.get("target_promo_id") == player_promo
                             or d.get("target_promo_id") is None)]
            sign_date = None
            for d in decisions:
                if d["decision_type"] == TYPE_SIGN:
                    sign_date = d["decision_date"]
                    break

            record_under_you = {"wins": 0, "losses": 0, "draws": 0}
            biggest_win = None
            if sign_date:
                fh_rows = conn.execute(
                    "SELECT fh.outcome, fh.result_type, fh.opponent_id, "
                    "  fh.event_id, fh.event_date, "
                    "  opp.first_name, opp.last_name, "
                    "  ev.event_name "
                    "FROM fight_history fh "
                    "LEFT JOIN fighters opp ON opp.fighter_id = fh.opponent_id "
                    "LEFT JOIN events ev ON ev.event_id = fh.event_id "
                    "WHERE fh.fighter_id=? AND fh.event_date >= ? "
                    "ORDER BY fh.event_date DESC",
                    (fid, sign_date),
                ).fetchall()
                for r in fh_rows:
                    outcome = r[0]
                    if outcome == "win":
                        record_under_you["wins"] += 1
                        if biggest_win is None:
                            biggest_win = {
                                "method": _result_type_label(r[1]),
                                "opponent_id": r[2],
                                "opponent_name": f"{r[5]} {r[6]}" if r[5] else "Unknown",
                                "event_name": r[7] or "",
                                "event_date": r[4] or "",
                            }
                    elif outcome == "loss":
                        record_under_you["losses"] += 1
                    elif outcome == "draw":
                        record_under_you["draws"] += 1

            contract_months = None
            contract_salary = None
            contract_expires_in_days = None
            crow = conn.execute(
                "SELECT c.start_date, c.end_date, c.salary FROM contracts c "
                "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
                "WHERE fc.fighter_id=? AND c.status='active' "
                "ORDER BY c.end_date DESC LIMIT 1",
                (fid,),
            ).fetchone()
            if crow:
                try:
                    s_dt = datetime.strptime(crow[0][:10], "%Y-%m-%d")
                    e_dt = datetime.strptime(crow[1][:10], "%Y-%m-%d")
                    contract_months = (e_dt.year - s_dt.year) * 12 + (e_dt.month - s_dt.month)
                except Exception:
                    contract_months = None
                contract_salary = float(crow[2] or 0)
                if sim_date:
                    try:
                        e_dt = datetime.strptime(crow[1][:10], "%Y-%m-%d")
                        s_dt = datetime.strptime(sim_date[:10], "%Y-%m-%d")
                        contract_expires_in_days = (e_dt - s_dt).days
                    except Exception:
                        contract_expires_in_days = None

            return {
                "decisions": decisions,
                "sign_date": sign_date,
                "contract_months": contract_months,
                "contract_salary": contract_salary,
                "contract_expires_in_days": contract_expires_in_days,
                "record_under_you": record_under_you,
                "biggest_win": biggest_win,
            }
        except Exception as e:
            print(f"[api.get_fighter_decision_history] {e}\n"
                  f"{traceback.format_exc()}", flush=True)
            return {"error": str(e)}

    def get_fighter_profile_data(self, fighter_id):
        """Return full Fighter Profile payload for `fighter_id`.

        Per SCREEN_DATA_AUDIT §4 + GUI_PLAN §6.3:
          - Header: name, nickname, age, wc, promo, gym, identity strip
            (6 LONG voice phrases), action button context.
          - Bio: from fighter_bios.bio_text.
          - Career stats: record, streak, title_reigns, career_health.
          - Recent Fights: last 10 fight_history rows with opponent info.
          - Attributes (26 StatBars): from fighter_descriptors.attribute_descriptors JSON.
          - Personality (20 StatBars): from fighter_descriptors.personality_descriptors JSON.
          - Title reigns: from titles.
          - News: last 10 news_items for this fighter.
          - Scouting report (if not player's fighter): from scouting_reports.
          - ALL voice phrases from interpretation layer. NEVER raw attributes.

        Returns dict with: header, bio, career_stats, recent_fights,
            attributes, personality, title_reigns, news, scouting_report.
        """
        try:
            fid = int(fighter_id)
            conn = self.conn
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None
            player_promo = self.get_player_promotion()

            # ----- Header -----
            # f[17] = portrait_path (TEXT, nullable). Added v3.19.0
            # (DB-REVIEW-IMAGE-ASSIGNMENT). Used to set header.has_portrait
            # — the actual base64 image is fetched separately via
            # get_fighter_portrait_b64() to avoid bloating the profile
            # payload (each .webp is 50-100KB).
            f = conn.execute(
                "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
                "f.gender, f.date_of_birth, f.weight_class_id, "
                "f.current_gym_id, f.current_promotion_id, "
                "f.birth_nation_id, f.stance, f.height_cm, f.reach_cm, "
                "f.fight_style_archetype_id, f.personality_archetype_id, "
                "f.is_active, f.is_retired, f.portrait_path "
                "FROM fighters f WHERE f.fighter_id = ?",
                (fid,),
            ).fetchone()
            if not f:
                return {"error": f"Fighter {fid} not found"}

            age = _compute_age(f[5], sim_date)
            wc_row = conn.execute(
                "SELECT name FROM weight_classes WHERE weight_class_id=?",
                (f[6],)
            ).fetchone()
            wc_name = wc_row[0] if wc_row else "—"

            promo_row = None
            if f[8]:
                promo_row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id=?",
                    (f[8],)
                ).fetchone()
            promo_name = promo_row[0] if promo_row else "Free Agent"

            gym_row = None
            if f[7]:
                gym_row = conn.execute(
                    "SELECT name FROM gyms WHERE gym_id=?",
                    (f[7],)
                ).fetchone()
            gym_name = gym_row[0] if gym_row else "—"

            nation_row = conn.execute(
                "SELECT name, nation_id FROM nations WHERE nation_id=?",
                (f[9],)
            ).fetchone()
            nat_code = _nation_iso3(nation_row[0] if nation_row else None,
                                    nation_row[1] if nation_row else None)

            style_row = None
            if f[13]:
                style_row = conn.execute(
                    "SELECT name, description FROM style_archetypes WHERE style_archetype_id=?",
                    (f[13],)
                ).fetchone()
            style_name = style_row[0] if style_row else "—"
            style_desc = style_row[1] if style_row else ""

            pers_row = None
            if f[14]:
                pers_row = conn.execute(
                    "SELECT name, description FROM personality_archetypes WHERE personality_archetype_id=?",
                    (f[14],)
                ).fetchone()
            pers_name = pers_row[0] if pers_row else "—"

            # ----- Descriptor (voice phrases) -----
            fd = conn.execute(
                "SELECT career_phase, career_phase_short, momentum, momentum_short, "
                "pressure, pressure_short, narrative_family, narrative_family_short, "
                "legacy_state, legacy_state_short, overall_desc, career_health_desc, "
                "attribute_descriptors, personality_descriptors, public_narrative, potential_desc "
                "FROM fighter_descriptors WHERE fighter_id=?",
                (fid,),
            ).fetchone()

            def _pair(stored_long, stored_short):
                """Return {long, short} voice phrase pair (decoded)."""
                return {
                    "long": _decode_phrase(stored_long) if stored_long else "",
                    "short": _decode_phrase(stored_short) if stored_short else "",
                    "label": _decode_label(stored_long) if stored_long else "",
                }

            identity_strip = {
                "career_phase": _pair(fd[0], fd[1]) if fd else {"long": "", "short": "", "label": ""},
                "momentum":     _pair(fd[2], fd[3]) if fd else {"long": "", "short": "", "label": ""},
                "pressure":     _pair(fd[4], fd[5]) if fd else {"long": "", "short": "", "label": ""},
                "narrative":    _pair(fd[6], fd[7]) if fd else {"long": "", "short": "", "label": ""},
                "legacy":       _pair(fd[8], fd[9]) if fd else {"long": "", "short": "", "label": ""},
                # trajectory uses potential_desc / public_narrative (often NULL — fall back to "")
                "trajectory":   {
                    "long": _decode_phrase(fd[15]) if fd and fd[15] else
                             (_decode_phrase(fd[14]) if fd and fd[14] else ""),
                    "short": "",
                    "label": "",
                },
            }

            overall_desc = fd[10] if fd else ""
            career_health_desc = fd[11] if fd else ""

            # Attribute + personality descriptor JSON
            attribute_descriptors = {}
            personality_descriptors = {}
            if fd and fd[12]:
                try:
                    attribute_descriptors = json.loads(fd[12])
                except Exception:
                    attribute_descriptors = {}
            if fd and fd[13]:
                try:
                    personality_descriptors = json.loads(fd[13])
                except Exception:
                    personality_descriptors = {}

            # ----- Career stats -----
            fc = conn.execute(
                "SELECT record_wins, record_losses, record_draws, win_streak, "
                "loss_streak, career_health, title_reigns, potential "
                "FROM fighter_career WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            career_stats = {
                "record_str": f"{fc[0] or 0}-{fc[1] or 0}-{fc[2] or 0}" if fc else "0-0-0",
                "wins": fc[0] if fc else 0,
                "losses": fc[1] if fc else 0,
                "draws": fc[2] if fc else 0,
                "win_streak": fc[3] if fc else 0,
                "loss_streak": fc[4] if fc else 0,
                "career_health": fc[5] if fc else 0,
                "title_reigns": fc[6] if fc else 0,
                # NOTE: potential INT is NEVER returned. career_health
                # is shown as a 0-100 number (it's a derived health
                # metric, not a hidden engine attribute).
            }

            # ----- Bio -----
            bio_row = conn.execute(
                "SELECT bio_text, bio_tone FROM fighter_bios WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            bio_text = bio_row[0] if bio_row else ""
            bio_tone = bio_row[1] if bio_row else ""

            # ----- Recent fights (last 10) -----
            fight_rows = conn.execute(
                "SELECT fh.fight_history_id, fh.opponent_id, fh.outcome, "
                "fh.result_type, fh.finish_round, fh.finish_time, "
                "fh.event_date, fh.title_at_stake, "
                "opp.first_name, opp.last_name, opp.nickname, "
                "wc.name AS wc_name "
                "FROM fight_history fh "
                "LEFT JOIN fighters opp ON opp.fighter_id = fh.opponent_id "
                "LEFT JOIN weight_classes wc ON wc.weight_class_id = fh.weight_class_id "
                "WHERE fh.fighter_id=? "
                "ORDER BY fh.event_date DESC LIMIT 10",
                (fid,),
            ).fetchall()
            recent_fights = []
            for r in fight_rows:
                opp_name = f"{r[8]} {r[9]}" if r[8] else "Unknown"
                opp_nickname = r[10] or ""
                badge = (r[2] or "n")[0].upper() if r[2] else "N"
                recent_fights.append({
                    "fight_history_id": r[0],
                    "opponent_id": r[1],
                    "opponent_name": opp_name,
                    "opponent_nickname": opp_nickname,
                    "outcome": r[2] or "n",
                    "badge": badge,
                    "result_type": r[3] or "",
                    "result_label": _result_type_label(r[3]),
                    "finish_round": r[4],
                    "finish_time": r[5] or "",
                    "event_date": r[6] or "",
                    "title_at_stake": bool(r[7]),
                    "wc_name": r[11] or "",
                })

            # Full fight history count
            total_fights = conn.execute(
                "SELECT COUNT(*) FROM fight_history WHERE fighter_id=?",
                (fid,),
            ).fetchone()[0]

            # ----- Title reigns -----
            title_rows = conn.execute(
                "SELECT t.title_id, wc.name, p.name AS promo_name, "
                "t.champion_since_date, t.title_reigns_count, t.title_defenses_count, "
                "t.is_vacant "
                "FROM titles t "
                "JOIN weight_classes wc ON wc.weight_class_id = t.weight_class_id "
                "LEFT JOIN promotions p ON p.promotion_id = t.promotion_id "
                "WHERE t.current_champion_fighter_id=? "
                "ORDER BY t.champion_since_date DESC",
                (fid,),
            ).fetchall()
            title_reigns = [{
                "title_id": t[0],
                "wc_name": t[1],
                "promo_name": t[2] or "",
                "champion_since_date": t[3] or "",
                "reign_length": _reign_length(t[3], sim_date) if t[3] else "—",
                "title_reigns_count": t[4] or 1,
                "title_defenses_count": t[5] or 0,
                "is_vacant": bool(t[6]),
            } for t in title_rows]
            is_champion = len(title_reigns) > 0

            # ----- News (last 10 for this fighter) -----
            news_rows = conn.execute(
                "SELECT news_item_id, headline, body, topic, published_at "
                "FROM news_items WHERE fighter_id=? "
                "ORDER BY published_at DESC LIMIT 10",
                (fid,),
            ).fetchall()
            news_items = [{
                "news_item_id": n[0],
                "headline": n[1] or "",
                "body": n[2] or "",
                "topic": n[3] or "wire",
                "published_at": n[4] or "",
            } for n in news_rows]

            # ----- Scouting report (if NOT player's fighter) -----
            scouting_report = None
            if f[8] != player_promo:
                sr = conn.execute(
                    "SELECT sr.report_date, sr.estimated_ceiling, sr.report_text, "
                    "sr.scout_confidence, sr.contract_cost_estimate, "
                    "st.first_name, st.last_name "
                    "FROM scouting_reports sr "
                    "LEFT JOIN staff st ON st.staff_id = sr.scout_id "
                    "WHERE sr.target_fighter_id=? "
                    "ORDER BY sr.report_date DESC LIMIT 1",
                    (fid,),
                ).fetchone()
                if sr:
                    scouting_report = {
                        "report_date": sr[0] or "",
                        "ceiling_phrase": sr[1] or "",
                        "report_text": sr[2] or "",
                        "confidence": _scout_confidence_phrase(sr[3]),
                        "cost_estimate": sr[4],
                        "scout_name": (f"{sr[5]} {sr[6]}" if sr[5] else "Unknown Scout"),
                    }

            # ----- Action button context -----
            is_on_player_roster = (f[8] == player_promo) and (f[15] == 1)
            is_free_agent = (f[8] is None) and (f[15] == 1) and (f[16] == 0)

            # ----- Active contract (for "Offer Extension" enablement) -----
            contract_info = None
            crow = conn.execute(
                "SELECT c.end_date, c.salary FROM contracts c "
                "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
                "WHERE fc.fighter_id=? AND c.status='active' "
                "ORDER BY c.end_date DESC LIMIT 1",
                (fid,),
            ).fetchone()
            if crow:
                contract_info = {
                    "end_date": crow[0] or "",
                    "salary": float(crow[1] or 0),
                    "expiring_soon": _is_expiring_soon(crow[0], sim_date, 90),
                }

            # ----- "Your History with [Fighter]" (Phase R §4) -----
            # Computed only for fighters on the player's roster. Returns:
            #   sign_date          — earliest TYPE_SIGN decision date
            #   contract_months    — months from contract.start_date to end_date
            #   contract_salary    — from active contracts row
            #   contract_expires_in_days — (end_date - sim_date) in days
            #   record_under_you   — {wins, losses, draws} since sign_date
            #   biggest_win        — {method, opponent_id, opponent_name,
            #                         event_name, event_date} or None
            #   decisions          — full chronological list (for timeline)
            your_history = None
            if is_on_player_roster and player_promo:
                try:
                    from player_decisions import (
                        get_decisions_for_fighter, TYPE_SIGN,
                    )
                    decisions = get_decisions_for_fighter(conn, fid)
                    # Filter to decisions for this promo (in case the
                    # fighter has history with multiple promos).
                    decisions = [d for d in decisions
                                 if (d.get("target_promo_id") == player_promo
                                     or d.get("target_promo_id") is None)]
                    sign_date = None
                    for d in decisions:
                        if d["decision_type"] == TYPE_SIGN:
                            sign_date = d["decision_date"]
                            break
                    # Compute record-under-you from fight_history since sign_date.
                    record_under_you = {"wins": 0, "losses": 0, "draws": 0}
                    biggest_win = None
                    if sign_date:
                        fh_rows = conn.execute(
                            "SELECT fh.outcome, fh.result_type, fh.opponent_id, "
                            "  fh.event_id, fh.event_date, "
                            "  opp.first_name, opp.last_name, "
                            "  ev.event_name "
                            "FROM fight_history fh "
                            "LEFT JOIN fighters opp ON opp.fighter_id = fh.opponent_id "
                            "LEFT JOIN events ev ON ev.event_id = fh.event_id "
                            "WHERE fh.fighter_id=? AND fh.event_date >= ? "
                            "ORDER BY fh.event_date DESC",
                            (fid, sign_date),
                        ).fetchall()
                        for r in fh_rows:
                            outcome = r[0]
                            if outcome == "win":
                                record_under_you["wins"] += 1
                                # Track biggest win: title fight > KO/TKO > SUB > decision
                                # (use first win found as fallback)
                                if biggest_win is None:
                                    biggest_win = {
                                        "method": _result_type_label(r[1]),
                                        "opponent_id": r[2],
                                        "opponent_name": f"{r[5]} {r[6]}" if r[5] else "Unknown",
                                        "event_name": r[7] or "",
                                        "event_date": r[4] or "",
                                    }
                            elif outcome == "loss":
                                record_under_you["losses"] += 1
                            elif outcome == "draw":
                                record_under_you["draws"] += 1
                    # Contract info from contracts row.
                    contract_months = None
                    contract_salary = None
                    contract_expires_in_days = None
                    if crow:
                        end_date = crow[0]
                        # Find start_date to compute contract_months.
                        start_row = conn.execute(
                            "SELECT c.start_date, c.end_date, c.salary "
                            "FROM contracts c "
                            "JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
                            "WHERE fc.fighter_id=? AND c.status='active' "
                            "ORDER BY c.end_date DESC LIMIT 1",
                            (fid,),
                        ).fetchone()
                        if start_row:
                            try:
                                s_dt = datetime.strptime(start_row[0][:10], "%Y-%m-%d")
                                e_dt = datetime.strptime(start_row[1][:10], "%Y-%m-%d")
                                contract_months = (e_dt.year - s_dt.year) * 12 + (e_dt.month - s_dt.month)
                            except Exception:
                                contract_months = None
                            contract_salary = float(start_row[2] or 0)
                        if end_date:
                            try:
                                e_dt = datetime.strptime(end_date[:10], "%Y-%m-%d")
                                s_dt = datetime.strptime(sim_date[:10], "%Y-%m-%d")
                                contract_expires_in_days = (e_dt - s_dt).days
                            except Exception:
                                contract_expires_in_days = None
                    your_history = {
                        "sign_date": sign_date,
                        "contract_months": contract_months,
                        "contract_salary": contract_salary,
                        "contract_expires_in_days": contract_expires_in_days,
                        "record_under_you": record_under_you,
                        "biggest_win": biggest_win,
                        "decisions": decisions,
                    }
                except Exception as e:
                    print(f"[api.get_fighter_profile_data] your_history "
                          f"failed: {e}", flush=True)
                    your_history = None

            return {
                "fighter_id": fid,
                "header": {
                    "fighter_id": fid,
                    "name": f"{f[1]} {f[2]}",
                    "first_name": f[1],
                    "last_name": f[2],
                    "nickname": f[3] or "",
                    "age": age,
                    "gender": f[4] or "",
                    "wc_name": wc_name,
                    "wc_id": f[6],
                    "promo_name": promo_name,
                    "promo_id": f[8],
                    "gym_name": gym_name,
                    "gym_id": f[7],
                    "nat_code": nat_code,
                    "stance": f[10] or "",
                    "height_cm": f[11],
                    "reach_cm": f[12],
                    "style_name": style_name,
                    "style_desc": style_desc,
                    "personality_archetype_name": pers_name,
                    "is_active": bool(f[15]),
                    "is_retired": bool(f[16]),
                    # DB-REVIEW-IMAGE-ASSIGNMENT E.4: has_portrait tells
                    # the UI to call get_fighter_portrait_b64() to fetch
                    # the image. The base64 is NOT embedded here (would
                    # bloat the profile payload by 50-100KB per image).
                    "has_portrait": bool(f[17]),
                    "is_champion": is_champion,
                    "is_on_player_roster": is_on_player_roster,
                    "is_free_agent": is_free_agent,
                    # Phase 5 Task 3: is_watched drives the ★ Watch /
                    # ★ Unwatch button state in the fighter profile
                    # header. Computed via the player_decisions watch/
                    # unwatch pattern (latest decision wins). Always
                    # False for fighters not on the player's promo
                    # (you can only watch your own roster).
                    "is_watched": (is_on_player_roster
                                   and self._is_fighter_currently_watched(fid)),
                    "overall_desc": overall_desc,
                    "career_health_desc": career_health_desc,
                    "identity_strip": identity_strip,
                },
                "bio": {
                    "text": bio_text,
                    "tone": bio_tone,
                },
                "career_stats": career_stats,
                "recent_fights": recent_fights,
                "total_fights": total_fights,
                "attributes": attribute_descriptors,
                "personality": personality_descriptors,
                "title_reigns": title_reigns,
                "news": news_items,
                "scouting_report": scouting_report,
                "contract": contract_info,
                "your_history": your_history,
                # CR-2 (docs/CR1_4_PLAN.md §2.4): per-attribute trajectory
                # chips for the Attributes tab. Additive — old JS that
                # doesn't read this key still works.
                "attribute_trajectory": _compute_attribute_trajectory(
                    conn, fid, sim_date),
                "sim_date": sim_date,
            }
        except Exception as e:
            print(f"[api.get_fighter_profile_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    def get_fighter_portrait_b64(self, fighter_id):
        """Return {has_portrait, portrait_b64, mime_type, data_uri} for a fighter.

        DB-REVIEW-IMAGE-ASSIGNMENT E.4: reads the fighter's
        portrait_path, loads the image file, base64-encodes it, and
        returns a data URI for the UI to render. Caches in-memory
        after first load (per user directive: "image will never
        change once linked" — regens work differently and get a new
        fighter_id, so the cached payload stays valid for the
        lifetime of this fighter_id).

        Defensive magic-byte check: 263 of the 415 uploaded .webp
        files are corrupted (all-null byte content — the RIFF....WEBP
        magic header is missing). For corrupted files, returns
        {has_portrait: False} so the UI gracefully degrades to the
        placeholder initial instead of showing a broken-image icon.
        This is safe to cache because the file never changes.

        Returns {has_portrait: False} if:
          - fighter_id is invalid / not found
          - portrait_path is NULL
          - file doesn't exist on disk
          - file is corrupted (no RIFF....WEBP magic in first 12 bytes)
        """
        try:
            fid = int(fighter_id)
            # Check cache (instance-level — survives across calls
            # within the same Api instance / pywebview session).
            if not hasattr(self, '_portrait_cache'):
                self._portrait_cache = {}
            if fid in self._portrait_cache:
                return self._portrait_cache[fid]

            row = self.conn.execute(
                "SELECT portrait_path FROM fighters WHERE fighter_id=?",
                (fid,)
            ).fetchone()
            if not row or not row[0]:
                result = {"has_portrait": False}
                self._portrait_cache[fid] = result
                return result

            # portrait_path is stored relative to data/ (e.g.
            # 'portraits/batch_001-020/batch_001-020/0001_*.webp').
            # DB_PATH = data/cage_empire.db, so DB_PATH.parent = data/.
            portrait_path = DB_PATH.parent / row[0]
            if not portrait_path.exists():
                result = {"has_portrait": False}
                self._portrait_cache[fid] = result
                return result

            # Read the file + magic-byte check (defensive against
            # corrupted all-null files discovered by verify_portraits.py).
            # CR-15: support both .png (new) and .webp (legacy) formats.
            with open(portrait_path, 'rb') as fh:
                img_bytes = fh.read()
            ext = portrait_path.suffix.lower()
            is_valid = False
            if ext == '.png' and len(img_bytes) >= 8:
                is_valid = img_bytes[:8] == b'\x89PNG\r\n\x1a\n'
            elif ext == '.webp' and len(img_bytes) >= 12:
                is_valid = img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP'
            if not is_valid:
                # Not a valid image file — likely a corrupted upload.
                # Don't print a warning here (would spam on every
                # fighter profile view); the verify_portraits.py
                # script already surfaces the full corruption list.
                result = {"has_portrait": False}
                self._portrait_cache[fid] = result
                return result

            b64 = base64.b64encode(img_bytes).decode('ascii')
            ext = portrait_path.suffix.lower()
            mime = 'image/webp' if ext == '.webp' else f'image/{ext[1:]}'

            result = {
                "has_portrait": True,
                "portrait_b64": b64,
                "mime_type": mime,
                "data_uri": f"data:{mime};base64,{b64}",
            }
            self._portrait_cache[fid] = result
            return result
        except Exception as e:
            print(f"[api.get_fighter_portrait_b64] {e}", flush=True)
            return {"has_portrait": False}

    # ============================================================
    # EVENT BUILDER (Phase E3.1 — Player Financial Levers)
    # ============================================================

    def get_event_builder_data(self):
        """Return everything the Event Builder screen needs to render.

        Per docs/PHASE_E3_PLAN.md §1.E3.1 + docs/ECON_STAFF_PLAN.md §3.3:
          - player promo info (cash, reputation, fan_trust, broadcast_tier)
          - available venues (venue_id, name, city_name, capacity,
            venue_type, rental_cost_per_seat)
          - weight classes
          - eligible fighters (player's active roster grouped by WC)

        NO raw potential exposed. The roster list returns only
        fighter_id + name + wc_name + record_str + stage_short — enough
        to populate a "your available talent" sidebar without leaking
        ceiling/potential numbers.

        Returns:
          {
            promo: {id, name, current_cash, cash_display,
                    reputation, reputation_phrase, fan_trust,
                    fan_trust_phrase, broadcast_tier, can_run_ppv},
            venues: [...],          # each venue carries nation_id/name +
                                   # region_id/name (Phase P2.2)
            countries: [{id, name}],   # unique countries (Phase P2.2)
            regions: [{id, name, country_id}],   # unique regions (P2.2)
            default_event_name: str,  # auto-name e.g. "Alpha Combat 15"
            weight_classes: [...],
            fighters_by_wc: {wc_id: {wc_name, fighters: [...]}}
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"error": "No player promotion selected."}
            conn = self.conn

            # --- promo info ---
            # F3: include size_tier so the JS Quick Pick can recommend
            # the best capacity/cost venue for the player's promo size.
            p = conn.execute(
                "SELECT promotion_id, name, current_cash, reputation, "
                "fan_trust, broadcast_tier, size_tier, starting_budget "
                "FROM promotions WHERE promotion_id=?", (pid,)
            ).fetchone()
            if not p:
                return {"error": f"Promotion {pid} not found."}
            cash = float(p[2] or 0)
            can_run_ppv = (p[5] in ("ppv_global", "ppv_streaming"))
            promo = {
                "id": p[0],
                "name": p[1],
                "current_cash": cash,
                "cash_display": _format_cash(cash),
                "is_cash_negative": cash < 0,
                "reputation": p[3],
                "reputation_phrase": _reputation_phrase(p[3] or 50),
                "fan_trust": p[4],
                "fan_trust_phrase": _fan_trust_phrase(p[4] or 50),
                "broadcast_tier": p[5] or "local_stream",
                "can_run_ppv": can_run_ppv,
                "size_tier": p[6] or "small",
                "starting_budget": float(p[7] or 0),
            }

            # --- venues ---
            # Per spec, the player picks a venue from the available list.
            # Show all venues with city name + capacity + venue_type +
            # rental_cost_per_seat (from finance._VENUE_COST_PER_SEAT_BY_TYPE).
            # Phase E6 will add a "regional availability" filter; for now
            # we expose the full list and let the UI filter by capacity.
            #
            # F3 (docs/FIX_PLAN_CACHE_CASH_EB.md §3) — augment each venue
            # with:
            #   - icon          (emoji based on venue_type: 🏟/🏛/🎭/🌳)
            #   - nation_name   (from city → nation join)
            #   - nation_flag   (regional-indicator flag emoji: 🇺🇸, 🇧🇷…)
            # These drive the visually richer venue cards in event_builder.js.
            from finance import (
                _VENUE_COST_PER_SEAT_BY_TYPE,
                _DEFAULT_VENUE_COST_PER_SEAT,
            )
            # Phase P2.2 — JOIN through cities → regions + nations so the
            # venue grid can filter by country + region (per docs/
            # COMPREHENSIVE_FIX_PLAN.md §Group B #6). Each venue row now
            # carries country_id/name + region_id/name alongside the
            # existing nation_name/flag. The unique country + region
            # lists are returned at the top level so the JS can populate
            # the filter dropdowns without re-scanning the venue list.
            v_rows = conn.execute(
                "SELECT v.venue_id, v.name, c.name, v.capacity, "
                "v.venue_type, n.nation_id, n.name, "
                "r.region_id, r.name "
                "FROM venues v "
                "JOIN cities c ON c.city_id = v.city_id "
                "LEFT JOIN nations n ON n.nation_id = c.nation_id "
                "LEFT JOIN regions r ON r.region_id = c.region_id "
                "ORDER BY v.capacity ASC"
            ).fetchall()
            venues = []
            countries_seen = {}   # country_id -> {id, name}
            regions_seen = {}     # region_id -> {id, name, country_id}
            for r in v_rows:
                (vid, vname, city_name, cap, vtype,
                 nation_id, nation_name,
                 region_id, region_name) = r
                vtype_resolved = vtype or "ballroom"
                cost_per_seat = _VENUE_COST_PER_SEAT_BY_TYPE.get(
                    vtype_resolved, _DEFAULT_VENUE_COST_PER_SEAT,
                )
                # Index the unique countries + regions for the dropdowns.
                if nation_id is not None:
                    countries_seen.setdefault(nation_id, {
                        "id": nation_id,
                        "name": nation_name or "International",
                    })
                if region_id is not None:
                    regions_seen.setdefault(region_id, {
                        "id": region_id,
                        "name": region_name or "—",
                        "country_id": nation_id,
                    })
                venues.append({
                    "venue_id": vid,
                    "name": vname,
                    "city_name": city_name,
                    "capacity": cap,
                    "venue_type": vtype_resolved,
                    "rental_cost_per_seat": cost_per_seat,
                    "rental_estimate": cap * cost_per_seat,
                    "icon": _venue_icon(vtype_resolved),
                    "nation_id": nation_id,
                    "nation_name": nation_name or "International",
                    "nation_flag": _nation_flag_emoji(nation_name),
                    "region_id": region_id,
                    "region_name": region_name or "",
                })
            # Sorted dropdown lists (alphabetical by name).
            countries = sorted(
                countries_seen.values(), key=lambda c: c["name"].lower(),
            )
            regions = sorted(
                regions_seen.values(), key=lambda r: r["name"].lower(),
            )

            # --- weight classes ---
            wc_rows = conn.execute(
                "SELECT weight_class_id, name, gender, display_order "
                "FROM weight_classes ORDER BY gender, "
                "COALESCE(display_order, weight_class_id)"
            ).fetchall()
            weight_classes = [{
                "id": r[0], "name": r[1],
                "gender": r[2],
            } for r in wc_rows]

            # --- eligible fighters (player's roster grouped by WC) ---
            # Voice-compliant: never returns raw potential. The roster
            # screen has the full attributes; the event builder just
            # needs a count + a sample for "who can headline this card".
            #
            # Phase 6 / Task B3 — LEFT JOIN fighter_career ONCE for the
            # whole roster (was: per-fighter SUM(...) FROM fight_history
            # subquery → N+1). fighter_career already maintains the
            # record_wins/losses/draws columns; reading them is cheaper
            # than re-aggregating fight_history per row.
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None
            f_rows = conn.execute(
                "SELECT f.fighter_id, f.first_name, f.last_name, "
                "f.date_of_birth, f.weight_class_id, wc.name, "
                "fd.career_phase_short, fd.momentum_short, "
                "fc.record_wins, fc.record_losses, fc.record_draws "
                "FROM fighters f "
                "LEFT JOIN weight_classes wc "
                "  ON wc.weight_class_id = f.weight_class_id "
                "LEFT JOIN fighter_descriptors fd "
                "  ON fd.fighter_id = f.fighter_id "
                "LEFT JOIN fighter_career fc "
                "  ON fc.fighter_id = f.fighter_id "
                "WHERE f.current_promotion_id=? AND f.is_active=1 "
                "  AND f.is_retired=0 "
                "ORDER BY wc.gender, COALESCE(wc.display_order, "
                "  wc.weight_class_id), f.last_name",
                (pid,),
            ).fetchall()
            fighters_by_wc = {}
            for r in f_rows:
                (fid, fn, ln, dob, wc_id, wc_name, stage_short, mom_short,
                 cwins, closses, cdraws) = r
                age = _compute_age(dob, sim_date)
                # Win-loss record from fighter_career (Phase 6 / B3 —
                # was previously a per-fighter SUM() subquery on
                # fight_history).
                w, l, d = (cwins or 0), (closses or 0), (cdraws or 0)
                record_str = f"{w}-{l}" + (f"-{d}" if d else "")
                wc_key = wc_id or 0
                if wc_key not in fighters_by_wc:
                    fighters_by_wc[wc_key] = {
                        "wc_id": wc_key,
                        "wc_name": wc_name or "—",
                        "fighters": [],
                    }
                fighters_by_wc[wc_key]["fighters"].append({
                    "fighter_id": fid,
                    "name": f"{fn} {ln}".strip(),
                    "age": age,
                    "record_str": record_str,
                    "stage_short": _decode_label(stage_short) if stage_short else "",
                    "momentum_short": _decode_label(mom_short) if mom_short else "",
                })

            # Phase P2.1 — pre-build the default event name so the JS
            # can pre-fill the NAME YOUR EVENT input. Format mirrors
            # create_event's auto-naming: "<Promo Name> <N>" where N =
            # next event number (existing event count + 1).
            n_events = conn.execute(
                "SELECT COUNT(*) FROM events WHERE promotion_id=?",
                (pid,),
            ).fetchone()[0]
            default_event_name = f"{promo['name']} {n_events + 1}"

            return {
                "promo": promo,
                "venues": venues,
                "countries": countries,
                "regions": regions,
                "default_event_name": default_event_name,
                "weight_classes": weight_classes,
                "fighters_by_wc": list(fighters_by_wc.values()),
            }
        except Exception as e:
            print(f"[api.get_event_builder_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"error": str(e)}

    def get_event_preview(self, params):
        """Return a projected revenue/expense breakdown for a candidate
        event WITHOUT creating the event row.

        Per docs/PHASE_E3_PLAN.md §1.E3.1 — the live preview shown as
        the player adjusts the levers. Mirrors the actual finance
        formulas used by finance._process_event_finance so the preview
        matches the eventual real P&L when the event completes.

        Phase M4 (docs/MASTER_PLAN_MATCHMAKING.md §1.3): when an
        `event_id` is provided AND the card has booked fights, the
        preview uses the REAL `card_draw_multiplier` formula via
        `_project_card_draw()` (replacing the hardcoded `1.2`).
        When no event_id is provided (Event Builder pre-event
        preview), the legacy `1.2` default is kept (no fights exist
        yet to score).

        MM1.4 (Matchmaking V2): a NEW `confirmed` parameter gates the
        projection. When `confirmed` is False (default — the player is
        still building the card), the projection is HIDDEN. The
        function returns:
          {ok: True, show_projection: False,
           message: "Confirm card to see projected revenue."}
        When `confirmed` is True (player clicked "Confirm Card" or
        the card is already locked), the full projection is returned
        as before.

        Args (params dict):
          venue_id, ticket_price, marketing_spend, ppv_price, is_ppv,
          event_id (optional — when present, real card_draw is used),
          confirmed (optional bool — when False, projection is hidden)

        Returns:
          When confirmed=False:
            {ok: True, show_projection: False, message: str}

          When confirmed=True (or param omitted, legacy callers):
            {
              ok: True,
              show_projection: True,
              attendance, fill_rate, gate, ppv_buys, ppv_revenue,
              broadcast_revenue, sponsorship, merch, concessions,
              total_revenue,
              fighter_purses, staff_salary, venue_rental,
              marketing_expense, insurance_medical,
              total_expenses, net_profit,
              cash_after_event, voice_phrase, voice_kind,
              card_draw, card_draw_score, card_draw_phrase,
              card_health_flags, n_fights_booked,
            }

        voice_kind ∈ {'safe','risky','lethal'} — drives the preview
        coloring + the "your war chest can absorb this" / "you're
        betting the farm" / "this could bankrupt you" voice phrases
        per docs/PHASE_E3_PLAN.md §2.
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn

            venue_id = int(params.get("venue_id") or 0)
            ticket_price = int(params.get("ticket_price") or 80)
            marketing_spend = int(params.get("marketing_spend") or 0)
            ppv_price = int(params.get("ppv_price") or 60)
            is_ppv = 1 if params.get("is_ppv") else 0
            event_id = int(params.get("event_id") or 0)
            # MM1.4 — `confirmed` gates the projection. Default is
            # True (legacy callers from the Event Builder still get
            # the full projection). The Matchmaking screen passes
            # confirmed=False during the build phase to hide the
            # projection until the player confirms the card.
            confirmed = params.get("confirmed")
            if confirmed is None:
                # Legacy default: show projection.
                confirmed = True
            else:
                confirmed = bool(confirmed)

            if not venue_id and not event_id:
                return {"ok": False, "error": "Pick a venue first."}

            # MM1.4 — gate the projection during the build phase.
            # When confirmed=False, return the "Confirm card to see
            # projected revenue" placeholder. The Matchmaking screen
            # uses this to keep the projection hidden until the
            # player commits to the card.
            if event_id and not confirmed:
                # Check whether the card is already locked (status
                # 'card_confirmed' or legacy scheduled-with-fights).
                # If so, fall through to compute the projection even
                # when confirmed=False was passed (backward compat).
                ev_status_row = conn.execute(
                    "SELECT status FROM events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                ev_status = ev_status_row[0] if ev_status_row else None
                n_fights_row = conn.execute(
                    "SELECT COUNT(*) FROM fights WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                n_fights = int(n_fights_row[0] or 0) if n_fights_row else 0
                already_locked = (
                    ev_status == 'card_confirmed'
                    or (ev_status == 'scheduled' and n_fights > 0)
                )
                if not already_locked:
                    return {
                        "ok": True,
                        "show_projection": False,
                        "message": "Confirm card to see projected revenue.",
                        "n_fights_booked": n_fights,
                    }
                # Already locked — fall through to compute projection.

            # If event_id is provided, prefer the event row's venue +
            # levers (the player may have changed levers on the event
            # row after creating it). Fall back to params for the
            # Event Builder pre-event path.
            if event_id:
                ev_row = conn.execute(
                    "SELECT e.venue_id, e.ticket_price, e.marketing_spend, "
                    "e.ppv_price, e.is_ppv, e.market_id, "
                    "v.capacity, v.venue_type, m.heat_level, "
                    "p.reputation, p.fan_trust, p.broadcast_tier, "
                    "p.current_cash "
                    "FROM events e "
                    "JOIN venues v ON v.venue_id=e.venue_id "
                    "JOIN markets m ON m.market_id=e.market_id "
                    "JOIN promotions p ON p.promotion_id=e.promotion_id "
                    "WHERE e.event_id=? AND e.promotion_id=?",
                    (event_id, pid),
                ).fetchone()
                if not ev_row:
                    return {"ok": False, "error": "Event not found."}
                (venue_id, ticket_price_ev, marketing_ev, ppv_ev, is_ppv_ev,
                 _market_id, venue_cap, venue_type, market_heat,
                 promo_rep, promo_trust, broadcast_tier,
                 current_cash) = ev_row
                # Params override the event row when provided (the JS
                # Matchmaking screen sends the current lever values from
                # the live state, not the persisted event row).
                if params.get("ticket_price") is None:
                    ticket_price = int(ticket_price_ev or 80)
                if params.get("marketing_spend") is None:
                    marketing_spend = int(marketing_ev or 0)
                if params.get("ppv_price") is None:
                    ppv_price = int(ppv_ev or 60)
                if params.get("is_ppv") is None:
                    is_ppv = int(is_ppv_ev or 0)
            else:
                if not venue_id:
                    return {"ok": False, "error": "Pick a venue first."}
                # Fetch venue + promo + market info.
                row = conn.execute(
                    "SELECT v.capacity, v.venue_type, m.heat_level, "
                    "p.reputation, p.fan_trust, p.broadcast_tier, "
                    "p.current_cash "
                    "FROM venues v "
                    "JOIN markets m ON m.city_id = v.city_id "
                    "JOIN promotions p ON p.promotion_id=? "
                    "WHERE v.venue_id=?",
                    (pid, venue_id),
                ).fetchone()
                if not row:
                    return {"ok": False, "error": "Venue not found."}
                (venue_cap, venue_type, market_heat, promo_rep, promo_trust,
                 broadcast_tier, current_cash) = row

            venue_cap = venue_cap or 5000
            market_heat = market_heat if market_heat is not None else 50
            promo_rep = max(0, min(100, promo_rep or 50))
            promo_trust = max(0, min(100, promo_trust or 50))

            # Use the real finance helpers so preview matches actual P&L.
            from finance import (
                _VENUE_COST_PER_SEAT_BY_TYPE,
                _DEFAULT_VENUE_COST_PER_SEAT,
                _PPV_BASE_BUYRATE,
                _FLAT_BROADCAST_RIGHTS,
                _BASE_SPONSOR_POOL,
                _DEFAULT_SPONSOR_POOL,
                _PPV_PLAYER_SPLIT,
                _CONCESSIONS_PER_ATTENDEE,
                _MERCH_PER_ATTENDEE_BASE,
                _MEDICAL_COST_PER_FIGHT,
                _N_EVENTS_PER_YEAR,
                _BASE_PURSE_MULTIPLIER,
                _MARKETING_FILL_BOOST_CAP,
                _MARKETING_PPV_MULT_CAP,
                _MARKETING_PPV_MULT_DIVISOR,
                _TICKET_PRICE_PENALTY_FACTOR,
                _TICKET_PRICE_PENALTY_FLOOR,
                _PPV_PRICE_PENALTY_FACTOR,
                _PPV_PRICE_PENALTY_FLOOR,
                _compute_fill_rate,
            )

            # --- fill_rate (Phase P2.4 — mirrors finance.py's new
            # _compute_fill_rate: heat + rep + marketing_boost -
            # price_penalty, clamped [0.10, 0.99]). The OLD preview
            # used a flat base_fill + 0.30-cap boost with NO price
            # elasticity, so maxing ticket_price still filled the
            # arena. Now maxing ticket_price to $300 floors fill at
            # 0.10 (almost empty arena) — matches the actual finance
            # path the player commits to when they schedule the event.
            fill_rate = _compute_fill_rate(
                market_heat,
                marketing_spend=marketing_spend,
                venue_capacity=venue_cap,
                ticket_price=ticket_price,
                promo_reputation=promo_rep,
            )
            attendance = int(venue_cap * fill_rate)

            # --- ticket revenue (player-set price) ---
            gate = attendance * ticket_price

            # --- card_draw ---
            # Phase M4: when event_id is provided, compute the REAL
            # card_draw_multiplier from the actual booked fights via
            # _project_card_draw (mirrors finance.py::_compute_broadcast_
            # revenue lines 384-390). When no event_id (Event Builder
            # pre-event preview), keep the legacy 1.2 default.
            card_draw_meta = None
            if event_id:
                try:
                    card_draw_meta = _project_card_draw(
                        conn, event_id,
                        levers={
                            "ticket_price": ticket_price,
                            "marketing_spend": marketing_spend,
                            "ppv_price": ppv_price,
                            "is_ppv": is_ppv,
                        },
                    )
                    card_draw = card_draw_meta["card_draw"]
                    avg_mkt = card_draw_meta["avg_card_marketability"] or 55
                    n_fights = card_draw_meta["n_fights"]
                except Exception as e:
                    print(f"[api.get_event_preview] card_draw fallback: {e}",
                          flush=True)
                    card_draw = 1.2
                    avg_mkt = 55
                    n_fights = 8
            else:
                card_draw = 1.2
                avg_mkt = 55
                n_fights = 8

            # --- broadcast + PPV (Phase P2.4 — mirrors finance.py's
            # _compute_broadcast_revenue: tighter 1.3 marketing cap +
            # ppv_price_penalty elasticity). The OLD preview used a 2.0
            # marketing cap + no PPV price elasticity, so maxing
            # marketing + PPV price to $80 + $500k doubled PPV buys.
            # Now maxing marketing tops out at +30% buys, and $80 PPV
            # costs 13% of buys — the player can't max-everything.
            ppv_buys = 0
            ppv_revenue = 0
            broadcast_revenue = 0
            if is_ppv and broadcast_tier in _PPV_BASE_BUYRATE:
                base_buyrate = _PPV_BASE_BUYRATE[broadcast_tier]
                # Phase P2.4: marketing_multiplier capped at 1.3 total
                # (was 2.0). The cap is on the TOTAL multiplier (1+delta),
                # so the delta caps at 0.3 (= 1.3 - 1.0). Mirrors
                # finance._compute_broadcast_revenue.
                marketing_multiplier = 1.0 + min(
                    _MARKETING_PPV_MULT_CAP - 1.0,
                    marketing_spend / _MARKETING_PPV_MULT_DIVISOR,
                )
                rep_factor = 0.5 + (promo_rep / 100.0)
                trust_factor = 0.5 + (promo_trust / 100.0)
                # Phase P2.4: PPV price elasticity — penalty above $60.
                ppv_price_penalty = 0.0
                if ppv_price > _PPV_PRICE_PENALTY_FLOOR:
                    ppv_price_penalty = (
                        (ppv_price - _PPV_PRICE_PENALTY_FLOOR) /
                        _PPV_PRICE_PENALTY_FLOOR
                    ) * _PPV_PRICE_PENALTY_FACTOR
                ppv_buys = int(base_buyrate * card_draw *
                               marketing_multiplier *
                               rep_factor * trust_factor *
                               (1.0 - ppv_price_penalty))
                # Use the player-set ppv_price.
                ppv_revenue = int(ppv_buys * ppv_price * _PPV_PLAYER_SPLIT)
                broadcast_revenue = ppv_revenue
            else:
                # Non-PPV: flat broadcast rights fee (per tier).
                broadcast_revenue = _FLAT_BROADCAST_RIGHTS.get(
                    broadcast_tier, 0)

            # --- sponsorship (mirrors finance._compute_sponsorship_revenue) ---
            base_pool = _BASE_SPONSOR_POOL.get(
                broadcast_tier, _DEFAULT_SPONSOR_POOL)
            sponsorship = int(base_pool *
                              (promo_rep / 100.0) *
                              (promo_trust / 100.0) * 2.0)

            # --- merch + concessions (per attendee) ---
            fan_trust_factor = 0.5 + (promo_trust / 100.0)
            merch = int(attendance * (avg_mkt / 100.0) *
                        fan_trust_factor * _MERCH_PER_ATTENDEE_BASE)
            concessions = int(attendance * _CONCESSIONS_PER_ATTENDEE)

            total_revenue = (gate + broadcast_revenue + sponsorship +
                             merch + concessions)

            # --- expenses ---
            # When n_fights comes from a real card, use it. Otherwise
            # assume 8 fights (mid-pack) for the pre-event preview.
            n_fights_for_expenses = max(1, n_fights) if n_fights else 8
            # Fighter purses: rough estimate — avg salary / 4 pro-rata ×
            # 1.5 multiplier × (n_fights × 2) fighters × ~2.0 for win
            # bonus (default 100% of base purse per P2.5). The old
            # preview used /6 × 1.25 (25% win bonus) — under-counted
            # fighter pay by ~60%. The new numbers mirror the actual
            # finance._process_event_finance path the player commits to.
            avg_salary_row = conn.execute(
                "SELECT AVG(c.salary) FROM fighter_contracts fc "
                "JOIN contracts c ON c.contract_id=fc.contract_id "
                "JOIN fighters f ON f.fighter_id=fc.fighter_id "
                "WHERE f.current_promotion_id=? AND c.status='active'",
                (pid,),
            ).fetchone()
            avg_salary = float(avg_salary_row[0] or 50000)
            # per_fighter base purse × win-bonus factor (avg 1.5 to
            # split between winners + losers; only winners get the
            # 100% win bonus, so the avg per-fighter payout ≈ base × 1.5).
            per_fighter_purse = (
                (avg_salary / _N_EVENTS_PER_YEAR) *
                _BASE_PURSE_MULTIPLIER * 1.5
            )
            fighter_purses = int(per_fighter_purse *
                                 (n_fights_for_expenses * 2))
            # Staff salary: sum of active staff_contracts / 12 pro-rata
            staff_row = conn.execute(
                "SELECT COALESCE(SUM(c.salary), 0) "
                "FROM staff_contracts sc "
                "JOIN contracts c ON c.contract_id=sc.contract_id "
                "WHERE c.promotion_id=? AND c.status='active'",
                (pid,),
            ).fetchone()
            staff_salary = int((float(staff_row[0] or 0)) /
                               _N_EVENTS_PER_YEAR)

            # Venue rental (player chose the venue).
            cost_per_seat = _VENUE_COST_PER_SEAT_BY_TYPE.get(
                venue_type or "ballroom", _DEFAULT_VENUE_COST_PER_SEAT,
            )
            venue_rental = venue_cap * cost_per_seat

            # Marketing spend (player-set).
            marketing_expense = marketing_spend

            # Insurance + medical: $5k flat + $3.5k per fight (per §3.2.5
            # mid-tier target's "5k + 8 × 3.5k = 33k" math).
            insurance_medical = 5000 + n_fights_for_expenses * 3500

            total_expenses = (fighter_purses + staff_salary +
                              venue_rental + marketing_expense +
                              insurance_medical)

            net_profit = total_revenue - total_expenses
            cash_after = current_cash + net_profit

            # Phase F1.3 (docs/FIX_PLAN_FINANCES_ADVANCEDAY.md §F1.3) —
            # pre-event preview shows a RANGE not a single number. Show
            # quality is unknown pre-event (the fights haven't happened
            # yet), so revenue varies ±30% based on how the show
            # actually performs. The low end assumes a dud (quality_
            # mult=0.80 → -20%), the high end assumes a blockbuster
            # (quality_mult=1.30 → +30%). Expenses are KNOWN precisely
            # (fighter purses, staff, venue, marketing, medical are
            # all set before the event) — no range on expenses.
            #
            # The range replaces the old single-number projection that
            # was misleadingly precise ("$8,085,751") — the player
            # should make decisions with the understanding that show
            # quality matters, not bank on a single number.
            revenue_range_low = int(total_revenue * 0.70)
            revenue_range_high = int(total_revenue * 1.30)
            net_range_low = revenue_range_low - total_expenses
            net_range_high = revenue_range_high - total_expenses
            cash_after_low = current_cash + net_range_low
            cash_after_high = current_cash + net_range_high
            voice_kind, voice_phrase = _voice_kind_for_net_range(
                net_range_low, net_range_high, current_cash,
            )

            result = {
                "ok": True,
                "attendance": attendance,
                "fill_rate": round(fill_rate, 3),
                "gate": gate,
                "ppv_buys": ppv_buys,
                "ppv_revenue": ppv_revenue,
                "broadcast_revenue": broadcast_revenue,
                "sponsorship": sponsorship,
                "merch": merch,
                "concessions": concessions,
                "total_revenue": total_revenue,
                "fighter_purses": fighter_purses,
                "staff_salary": staff_salary,
                "venue_rental": venue_rental,
                "marketing_expense": marketing_expense,
                "insurance_medical": insurance_medical,
                "total_expenses": total_expenses,
                # Legacy single-number fields — kept for backward
                # compat with any caller that still reads them. The UI
                # uses the *_range_* fields below instead. net_profit
                # is the midpoint of the range (the "expected" value
                # if show quality is average).
                "net_profit": net_profit,
                "cash_after_event": cash_after,
                "voice_phrase": voice_phrase,
                "voice_kind": voice_kind,
                "card_draw": round(card_draw, 3),
                "n_fights_booked": n_fights,
                # Phase F1.3 — RANGE fields (the new primary display).
                # The UI shows these as "Projected Revenue: $X.XM -
                # $Y.YM" + "Projected Net: $A.AM - $B.BM" + the voice
                # phrase. The single-number net_profit + cash_after
                # fields above are retained for callers that haven't
                # migrated yet (CTA bar, dashboard widget).
                "revenue_range_low": revenue_range_low,
                "revenue_range_high": revenue_range_high,
                "revenue_range_display": (
                    f"{_format_cash(revenue_range_low)} - "
                    f"{_format_cash(revenue_range_high)}"
                ),
                "net_range_low": net_range_low,
                "net_range_high": net_range_high,
                "net_range_display": (
                    f"{_format_cash(net_range_low)} - "
                    f"{_format_cash(net_range_high)}"
                ),
                "cash_after_range_low": cash_after_low,
                "cash_after_range_high": cash_after_high,
                "cash_after_range_display": (
                    f"{_format_cash(cash_after_low)} - "
                    f"{_format_cash(cash_after_high)}"
                ),
                # Pre-formatted display strings for the UI.
                "gate_display": _format_cash(gate),
                "broadcast_revenue_display": _format_cash(broadcast_revenue),
                "sponsorship_display": _format_cash(sponsorship),
                "merch_display": _format_cash(merch),
                "concessions_display": _format_cash(concessions),
                "total_revenue_display": _format_cash(total_revenue),
                "fighter_purses_display": _format_cash(fighter_purses),
                "staff_salary_display": _format_cash(staff_salary),
                "venue_rental_display": _format_cash(venue_rental),
                "marketing_expense_display": _format_cash(marketing_expense),
                "insurance_medical_display": _format_cash(insurance_medical),
                "total_expenses_display": _format_cash(total_expenses),
                "net_profit_display": _format_cash(net_profit),
                "cash_after_display": _format_cash(cash_after),
            }
            if card_draw_meta:
                result["card_draw_score"] = card_draw_meta["card_draw_score"]
                result["card_draw_phrase"] = card_draw_meta["card_draw_phrase"]
                result["card_health_flags"] = card_draw_meta["card_health_flags"]
                result["me_marketability"] = card_draw_meta["me_marketability"]
                result["co_marketability"] = card_draw_meta["co_marketability"]
                result["n_title_fights"] = card_draw_meta["n_title_fights"]
                result["n_rivalry_fights"] = card_draw_meta["n_rivalry_fights"]
                result["avg_card_marketability"] = card_draw_meta["avg_card_marketability"]
            else:
                result["card_draw_score"] = None
                result["card_draw_phrase"] = None
                result["card_health_flags"] = []
            # MM1.4 — flag that the projection is being shown (caller
            # can use this to differentiate from the build-phase
            # placeholder response).
            result["show_projection"] = True
            return result
        except Exception as e:
            print(f"[api.get_event_preview] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def confirm_card(self, event_id, fights):
        """Confirm a staged card by writing all fights to the DB in one
        transaction + computing the projection.

        Per docs/MASTER_PLAN_MATCHMAKING_V2.md §MM1.4 + §MM1.6:
          - Takes the event_id + list of staged fights (each with
            red_fighter_id, blue_fighter_id, card_slot).
          - Writes all fights to DB in one transaction (INSERT fights
            + fight_participants + event_cards rows).
          - Updates event status to 'card_confirmed' (so the card is
            visually locked + the projection can be shown).
          - Returns the full projection (revenue, expenses, net,
            voice phrase) so the JS can update the Status Panel.

        Args:
          event_id: int
          fights: list of dicts with red_fighter_id, blue_fighter_id,
                  card_slot (optional — auto-assigned by position if
                  not provided)

        Returns:
          {ok, fight_ids, n_fights, projection: {…same shape as
           get_event_preview with confirmed=True…}}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            eid = int(event_id or 0)
            if not eid:
                return {"ok": False, "error": "Missing event_id."}
            if not isinstance(fights, (list, tuple)):
                return {"ok": False, "error": "fights must be a list."}
            if not fights:
                return {"ok": False,
                        "error": "Cannot confirm an empty card."}

            # Phase P2.6 (docs/COMPREHENSIVE_FIX_PLAN.md §Group B #12) —
            # minimum fights per card based on promo size_tier. A major
            # promo can't run a 1-fight card (unrealistic); a small promo
            # can run a 3-fight club show. The check happens BEFORE any
            # DB writes so a rejected confirm doesn't leave a half-built
            # card in the transaction.
            promo_size_row = conn.execute(
                "SELECT size_tier FROM promotions WHERE promotion_id=?",
                (pid,),
            ).fetchone()
            promo_size_tier = (promo_size_row[0] if promo_size_row
                               else "small") or "small"
            min_fights_by_tier = {"major": 5, "mid": 4, "small": 3}
            min_fights = min_fights_by_tier.get(promo_size_tier, 3)
            if len(fights) < min_fights:
                # Voice-compliant error message per the brief — explains
                # the constraint + suggests the remedy (add fights OR
                # switch to a smaller venue/promo tier).
                tier_phrase = {
                    "major": "major",
                    "mid": "mid-tier",
                    "small": "small",
                }.get(promo_size_tier, "small")
                return {
                    "ok": False,
                    "error": (
                        f"A {tier_phrase} promotion needs at least "
                        f"{min_fights} fights on a card. "
                        f"Add more fights or switch to a smaller venue."
                    ),
                    "error_code": "min_fights_not_met",
                    "min_fights": min_fights,
                    "n_staged": len(fights),
                    "size_tier": promo_size_tier,
                }

            # Verify the event belongs to the player's promo + is in
            # a state where we can confirm (scheduled OR card_confirmed
            # — re-confirming is allowed, replaces the existing card).
            ev_row = conn.execute(
                "SELECT promotion_id, status FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row:
                return {"ok": False, "error": "Event not found."}
            if ev_row[0] != pid:
                return {"ok": False,
                        "error": "This event belongs to another promotion."}
            if ev_row[1] not in ('scheduled', 'card_confirmed'):
                return {"ok": False,
                        "error": f"Event status is '{ev_row[1]}' — can only "
                                 f"confirm 'scheduled' or 'card_confirmed'."}

            # If the event already has fights (re-confirm or backward
            # compat), wipe them first so the new staged card replaces
            # the old one cleanly.
            existing_fights_row = conn.execute(
                "SELECT COUNT(*) FROM fights WHERE event_id=?",
                (eid,),
            ).fetchone()
            if int(existing_fights_row[0] or 0) > 0:
                # Cascade delete removes fight_participants + event_cards.
                conn.execute(
                    "DELETE FROM fights WHERE event_id=?",
                    (eid,),
                )

            # Auto-assign card_slot if not provided (first = main_event,
            # second = co_main, etc.) + insert each fight + participants
            # + event_cards row in one transaction.
            new_fight_ids = []
            for idx, f in enumerate(fights):
                if not isinstance(f, dict):
                    conn.rollback()
                    return {"ok": False,
                            "error": f"fight at index {idx} must be a dict."}
                red_id = int(f.get("red_fighter_id") or 0)
                blue_id = int(f.get("blue_fighter_id") or 0)
                if not red_id or not blue_id:
                    conn.rollback()
                    return {"ok": False,
                            "error": f"fight at index {idx} missing fighter IDs."}
                if red_id == blue_id:
                    conn.rollback()
                    return {"ok": False,
                            "error": f"fight at index {idx}: same fighter."}
                card_slot = f.get("card_slot")
                if not card_slot:
                    if idx == 0:
                        card_slot = 'main_event'
                    elif idx == 1:
                        card_slot = 'co_main'
                    elif idx <= 3:
                        card_slot = 'featured_prelim'
                    else:
                        card_slot = 'prelim'
                valid_slots = ('main_event', 'co_main', 'featured_prelim',
                               'prelim', 'opener')
                if card_slot not in valid_slots:
                    conn.rollback()
                    return {"ok": False,
                            "error": f"fight at index {idx}: invalid card_slot."}
                # Verify both fighters exist + are on the player's promo
                # + same WC + same gender (defensive — should match the
                # JS-side checks).
                fr_row = conn.execute(
                    "SELECT fighter_id, weight_class_id, gender, "
                    "current_promotion_id, is_active, is_retired "
                    "FROM fighters WHERE fighter_id IN (?, ?)",
                    (red_id, blue_id),
                ).fetchall()
                if len(fr_row) != 2:
                    conn.rollback()
                    return {"ok": False,
                            "error": f"fight at index {idx}: fighter not found."}
                r = fr_row[0]
                b = fr_row[1]
                if r[0] != red_id:
                    r, b = b, r
                r_fid, r_wc, r_gender, r_promo, r_active, r_retired = r
                b_fid, b_wc, b_gender, b_promo, b_active, b_retired = b
                if r_promo != pid or b_promo != pid:
                    conn.rollback()
                    return {"ok": False,
                            "error": "Both fighters must be on your roster."}
                if not r_active or not b_active or r_retired or b_retired:
                    conn.rollback()
                    return {"ok": False,
                            "error": "Both fighters must be active."}
                if r_gender != b_gender:
                    conn.rollback()
                    return {"ok": False,
                            "error": "Mixed-gender fights aren't allowed."}
                if r_wc != b_wc:
                    conn.rollback()
                    return {"ok": False,
                            "error": "Fighters must be in the same weight class."}

                scheduled_rounds = 5 if card_slot == 'main_event' else 3
                new_fid = conn.execute(
                    "INSERT INTO fights (event_id, weight_class_id, "
                    "bout_type, card_slot, is_title_fight, round_limit, "
                    "scheduled_rounds) "
                    "VALUES (?, ?, ?, ?, 0, 3, ?)",
                    (eid, r_wc, card_slot, card_slot, scheduled_rounds),
                ).lastrowid
                conn.execute(
                    "INSERT INTO fight_participants (fight_id, fighter_id, "
                    "corner) VALUES (?, ?, 'red')",
                    (new_fid, red_id),
                )
                conn.execute(
                    "INSERT INTO fight_participants (fight_id, fighter_id, "
                    "corner) VALUES (?, ?, 'blue')",
                    (new_fid, blue_id),
                )
                conn.execute(
                    "INSERT INTO event_cards (event_id, fight_id, "
                    "card_position, card_tier, is_main_event, is_co_main) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (eid, new_fid, idx + 1, card_slot,
                     1 if card_slot == 'main_event' else 0,
                     1 if card_slot == 'co_main' else 0),
                )
                # Persist the punditry analysis for this fight (so
                # the chip + voice phrases are stable across reloads).
                # Defensive — failures here don't roll back the fight
                # write (the analysis is regenerated on FIGHT_RESOLVED
                # anyway).
                try:
                    from punditry import generate_matchup_analysis
                    generate_matchup_analysis(
                        conn, red_id, blue_id, fight_id=new_fid,
                        event_id=eid,
                    )
                except Exception as e:
                    print(f"[api.confirm_card] punditry: {e}", flush=True)
                new_fight_ids.append(new_fid)

            # Update event status to 'card_confirmed' (locks the card).
            conn.execute(
                "UPDATE events SET status='card_confirmed', "
                "updated_at=CURRENT_TIMESTAMP WHERE event_id=?",
                (eid,),
            )
            conn.commit()

            # Compute the projection (confirmed=True so the full
            # P&L is returned).
            projection = self.get_event_preview({
                "event_id": eid,
                "confirmed": True,
            })

            return {
                "ok": True,
                "event_id": eid,
                "fight_ids": new_fight_ids,
                "n_fights": len(new_fight_ids),
                "projection": projection,
            }
        except Exception as e:
            print(f"[api.confirm_card] {e}\n{traceback.format_exc()}",
                  flush=True)
            try:
                conn.rollback()
            except Exception:
                pass
            return {"ok": False, "error": str(e)}

    def reopen_card(self, event_id):
        """Re-open a confirmed card so the player can edit it again.

        Per docs/MASTER_PLAN_MATCHMAKING_V2.md §MM1.4: removes all
        fights from DB + resets event status to 'scheduled' (so the
        card goes back to the "build" state with projection hidden).

        Args:
          event_id: int

        Returns:
          {ok, event_id, removed_count}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            eid = int(event_id or 0)
            if not eid:
                return {"ok": False, "error": "Missing event_id."}

            ev_row = conn.execute(
                "SELECT promotion_id, status FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row:
                return {"ok": False, "error": "Event not found."}
            if ev_row[0] != pid:
                return {"ok": False,
                        "error": "This event belongs to another promotion."}
            if ev_row[1] not in ('scheduled', 'card_confirmed'):
                return {"ok": False,
                        "error": f"Event status is '{ev_row[1]}' — can only "
                                 f"reopen 'scheduled' or 'card_confirmed'."}

            # Count + delete all fights (cascade handles participants
            # + event_cards).
            cnt_row = conn.execute(
                "SELECT COUNT(*) FROM fights WHERE event_id=?",
                (eid,),
            ).fetchone()
            removed = int(cnt_row[0] or 0) if cnt_row else 0
            conn.execute("DELETE FROM fights WHERE event_id=?", (eid,))

            # Reset status to 'scheduled' (no fights → build phase).
            conn.execute(
                "UPDATE events SET status='scheduled', "
                "updated_at=CURRENT_TIMESTAMP WHERE event_id=?",
                (eid,),
            )
            conn.commit()

            return {
                "ok": True,
                "event_id": eid,
                "removed_count": removed,
            }
        except Exception as e:
            print(f"[api.reopen_card] {e}\n{traceback.format_exc()}",
                  flush=True)
            try:
                conn.rollback()
            except Exception:
                pass
            return {"ok": False, "error": str(e)}

    def create_event(self, params):
        """Create a scheduled event with player-set financial levers.

        Per docs/PHASE_E3_PLAN.md §1.E3.1 + docs/ECON_STAFF_PLAN.md §3.3.

        Args (params dict):
          venue_id, event_date, event_name,
          ticket_price, marketing_spend, ppv_price, is_ppv

        Writes a single row to the events table with status='scheduled'.
        Does NOT create any fights (that's the Matchmaking screen's job —
        Phase E3 is finance-only).

        Returns {ok, event_id, event_name, event_date}.
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn

            venue_id = int(params.get("venue_id") or 0)
            if not venue_id:
                return {"ok": False, "error": "Pick a venue first."}

            # Validate the venue has a market.
            vm_row = conn.execute(
                "SELECT m.market_id FROM venues v "
                "JOIN markets m ON m.city_id = v.city_id "
                "WHERE v.venue_id=?", (venue_id,),
            ).fetchone()
            if not vm_row:
                return {"ok": False, "error": "Venue has no market."}
            market_id = vm_row[0]

            # Event date — default to +14 days from current sim date.
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None
            event_date = params.get("event_date")
            if not event_date:
                if not sim_date:
                    return {"ok": False, "error": "No sim clock available."}
                dt = datetime.strptime(sim_date, "%Y-%m-%d")
                event_date = (dt + timedelta(days=14)).strftime("%Y-%m-%d")

            # Event name — default to "<Promo> <N>" if not provided.
            event_name = params.get("event_name") or ""
            if not event_name:
                promo_row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id=?",
                    (pid,),
                ).fetchone()
                promo_name = promo_row[0] if promo_row else "Cage Empire"
                n_events = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE promotion_id=?",
                    (pid,),
                ).fetchone()[0]
                event_name = f"{promo_name} {n_events + 1}"

            ticket_price = int(params.get("ticket_price") or 80)
            marketing_spend = int(params.get("marketing_spend") or 0)
            ppv_price = int(params.get("ppv_price") or 60)
            is_ppv = 1 if params.get("is_ppv") else 0

            # Sanity-clamp the levers to their documented ranges.
            ticket_price = max(20, min(300, ticket_price))
            marketing_spend = max(0, min(500000, marketing_spend))
            ppv_price = max(30, min(80, ppv_price))

            event_id = conn.execute(
                "INSERT INTO events (promotion_id, venue_id, market_id, "
                "event_name, event_date, event_type, status, "
                "ticket_price, marketing_spend, ppv_price, is_ppv) "
                "VALUES (?, ?, ?, ?, ?, 'fight_night', 'scheduled', "
                "?, ?, ?, ?)",
                (pid, venue_id, market_id, event_name, event_date,
                 ticket_price, marketing_spend, ppv_price, is_ppv),
            ).lastrowid

            conn.commit()
            return {
                "ok": True,
                "event_id": event_id,
                "event_name": event_name,
                "event_date": event_date,
            }
        except Exception as e:
            print(f"[api.create_event] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # PHASE MM2 — CALENDAR SCREEN API
    # Per docs/MASTER_PLAN_MATCHMAKING_V2.md §2 + docs/RESEARCH_WMMA5_FM_V2.md
    # §4 (Priority 4 — Calendar / scheduling). The player can finally
    # choose WHEN to schedule an event. Month grid shows player events
    # (gold) + rival promo events (red) + today (blue) + past dates
    # (greyed) + min-lead-time blocked (< 14 days from sim_date) +
    # conflict warnings (rival event within ±2 days → counter-programming
    # risk; own event within 7 days → short turnaround).
    # ============================================================

    def get_calendar_data(self, month=None, year=None):
        """Return calendar data for a given month.

        Per docs/MASTER_PLAN_MATCHMAKING_V2.md §2.1 (Calendar view) +
        §2.2 (Conflict warnings).

        Args:
          month: int 1-12 (defaults to current sim month)
          year:  int (defaults to current sim year)

        Returns:
          {
            "current_date": "2027-03-15",
            "month": 3,
            "year": 2027,
            "month_name": "March",
            "prev_month": {"month": 2, "year": 2027},
            "next_month": {"month": 4, "year": 2027},
            "player_promo_id": 1,
            "player_promo_name": "Cage Empire",
            "min_lead_days": 14,
            "days": [
              {
                "day": 1,
                "date": "2027-03-01",
                "weekday": 0,            # 0=Mon .. 6=Sun
                "is_today": false,
                "is_past": true,
                "is_future": false,
                "min_lead_time_blocked": false,  # < 14 days from sim_date
                "is_eligible": true,             # pickable (future + ≥14d)
                "player_events": [{"event_id", "event_name", "event_type"}],
                "rival_events":  [{"event_id", "event_name", "promo_name",
                                    "promo_id", "promo_logo_b64"}],
                "conflicts": ["rival event within ±2 days",
                              "own event within 7 days"],
                "has_conflict": true
              }, ...
            ]
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn

            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            try:
                sim_dt = datetime.strptime(sim_date_str, "%Y-%m-%d") if sim_date_str else None
            except (ValueError, TypeError):
                sim_dt = None

            # Default month/year to sim date.
            if month is None or year is None:
                if sim_dt:
                    m_, y_ = sim_dt.month, sim_dt.year
                else:
                    m_, y_ = 1, 2026
            else:
                m_, y_ = int(month), int(year)
            # Normalize month to 1-12 (year rolls over).
            while m_ < 1:
                m_ += 12; y_ -= 1
            while m_ > 12:
                m_ -= 12; y_ += 1

            month_name = calendar.month_name[m_] if 1 <= m_ <= 12 else ""
            prev_m, prev_y = (m_ - 1, y_) if m_ > 1 else (12, y_ - 1)
            next_m, next_y = (m_ + 1, y_) if m_ < 12 else (1, y_ + 1)

            # Promo name for header.
            p_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?", (pid,),
            ).fetchone()
            player_promo_name = p_row[0] if p_row else "Your Promotion"

            # --- fetch all events for this month (any promo, scheduled
            # or card_confirmed — NOT completed/cancelled). Single SQL
            # query → fast (<100ms for any reasonable event count). ---
            first_of_month = datetime(y_, m_, 1)
            if m_ == 12:
                first_of_next = datetime(y_ + 1, 1, 1)
            else:
                first_of_next = datetime(y_, m_ + 1, 1)

            ev_rows = conn.execute(
                "SELECT e.event_id, e.event_name, e.event_date, "
                "e.event_type, e.promotion_id, p.name "
                "FROM events e "
                "LEFT JOIN promotions p ON p.promotion_id = e.promotion_id "
                "WHERE e.event_date >= ? AND e.event_date < ? "
                "  AND e.status IN ('scheduled', 'card_confirmed') "
                "ORDER BY e.event_date ASC",
                (first_of_month.strftime("%Y-%m-%d"),
                 first_of_next.strftime("%Y-%m-%d")),
            ).fetchall()

            # Cache rival promo logos (1 lookup per rival promo) so we
            # don't hit the filesystem once per day cell.
            rival_logo_cache = {}
            # Group events by date string.
            events_by_date = {}
            for r in ev_rows:
                (eid, ename, edate, etype, epromo, pname) = r
                ev = {
                    "event_id": eid,
                    "event_name": ename or "",
                    "event_type": etype or "fight_night",
                }
                if epromo == pid:
                    ev_dict = events_by_date.setdefault(edate, {"player": [], "rival": []})
                    ev_dict["player"].append(ev)
                else:
                    if epromo not in rival_logo_cache:
                        rival_logo_cache[epromo] = _load_logo_b64(epromo)
                    ev["promo_id"] = epromo
                    ev["promo_name"] = pname or "Rival Promo"
                    ev["promo_logo_b64"] = rival_logo_cache[epromo]
                    ev_dict = events_by_date.setdefault(edate, {"player": [], "rival": []})
                    ev_dict["rival"].append(ev)

            # --- Build the month grid. ---
            # Use calendar.monthrange to get the first weekday + total
            # days in the month. Monday-first (matches WMMA5 calendar).
            first_weekday, n_days = calendar.monthrange(y_, m_)

            # For conflict detection, we need to know about events in
            # the surrounding days (±7 for own, ±2 for rival). Pre-fetch
            # a wider window of events so per-day conflict logic is O(1).
            days = []
            conflict_window_start = (first_of_month - timedelta(days=7)).strftime("%Y-%m-%d")
            conflict_window_end = (first_of_next + timedelta(days=7)).strftime("%Y-%m-%d")
            conflict_rows = conn.execute(
                "SELECT e.event_id, e.event_name, e.event_date, e.promotion_id, p.name "
                "FROM events e "
                "LEFT JOIN promotions p ON p.promotion_id = e.promotion_id "
                "WHERE e.event_date >= ? AND e.event_date < ? "
                "  AND e.status IN ('scheduled', 'card_confirmed')",
                (conflict_window_start, conflict_window_end),
            ).fetchall()
            # Phase 7 / Task A3 — replace the O(N×M) nested loop with
            # an O(N+M) date-keyed dict lookup. The previous code
            # iterated `rival_dates` + `player_dates` lists per day
            # (31 days × ~50 events × datetime.strptime → up to ~1550
            # strptime calls per call). The new code builds an
            # ``events_by_date_window`` dict ONCE (keyed by date_str),
            # pre-parses each date_str into a datetime ONCE, then per
            # day iterates ±7 offsets (15 dict lookups, no strptime).
            events_by_date_window = {}  # date_str → {"player":[(ename,dt)], "rival":[(ename,pname,dt)]}
            for r in conflict_rows:
                (_eid, ename, edate, epromo, pname) = r
                try:
                    e_dt = datetime.strptime(edate, "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                bucket = events_by_date_window.setdefault(
                    edate, {"player": [], "rival": []})
                if epromo == pid:
                    bucket["player"].append((ename or "", e_dt))
                else:
                    bucket["rival"].append((ename or "", pname or "Rival", e_dt))

            today_str = sim_date_str
            # Pre-compute the ±7-day offset datetimes ONCE per calendar
            # day. Each per-day conflict scan is then a flat 15-iteration
            # loop with dict lookups — no strptime inside.
            one_day = timedelta(days=1)
            for d in range(1, n_days + 1):
                date_str = f"{y_:04d}-{m_:02d}-{d:02d}"
                date_dt = datetime(y_, m_, d)
                is_today = (today_str == date_str)
                is_past = False
                is_future = False
                if sim_dt:
                    if date_dt.date() < sim_dt.date():
                        is_past = True
                    elif date_dt.date() > sim_dt.date():
                        is_future = True
                # Min-lead-time: < 14 days from sim_date AND in the future.
                min_lead_blocked = False
                if sim_dt and date_dt.date() >= sim_dt.date():
                    delta_days = (date_dt.date() - sim_dt.date()).days
                    if delta_days < 14:
                        min_lead_blocked = True
                is_eligible = (sim_dt is None) or (
                    date_dt.date() > sim_dt.date() and not min_lead_blocked
                )

                # Events on this day.
                ed = events_by_date.get(date_str, {"player": [], "rival": []})
                player_events = ed["player"]
                rival_events = ed["rival"]

                # Conflicts (per spec §2.2):
                #   rival event within ±2 days → counter-programming risk
                #   own event within 7 days → short turnaround
                #
                # Phase 7 / Task A3 — iterate ±7 offsets (15 total) with
                # dict lookups instead of scanning rival_dates/player_dates
                # lists linearly per day. Skips offset=0 (same-day, handled
                # by the player_events / rival_events slots above).
                conflicts = []
                if not is_past:
                    offset_dt = date_dt - timedelta(days=7)
                    for offset in range(-7, 8):
                        if offset == 0:
                            offset_dt = date_dt
                            continue
                        # Walk offset_dt forward by 1 day each iteration —
                        # no strptime, no re-allocation.
                        bucket = events_by_date_window.get(
                            offset_dt.strftime("%Y-%m-%d"))
                        if bucket:
                            # Rival conflicts only matter within ±2 days.
                            if -2 <= offset <= 2 and bucket["rival"]:
                                for (r_ename, r_pname, _r_dt) in bucket["rival"]:
                                    weekday_str = offset_dt.strftime("%a")
                                    conflicts.append(
                                        f"{r_pname} is running '{r_ename}' on "
                                        f"{weekday_str} — counter-programming will "
                                        f"split the gate."
                                    )
                                    break
                            # Player conflicts matter within ±7 days.
                            if bucket["player"]:
                                for (o_ename, _o_dt) in bucket["player"]:
                                    weekday_str = offset_dt.strftime("%a")
                                    conflicts.append(
                                        f"You're already running '{o_ename}' on "
                                        f"{weekday_str} — short turnaround."
                                    )
                                    break
                        offset_dt = offset_dt + one_day
                    # Deduplicate — same rival/player event could appear
                    # at multiple offsets (rare but possible if ±2 and
                    # ±7 windows overlap for the same neighbor day). The
                    # original code broke on first match per category;
                    # the dict-lookup version surfaces ALL neighbor days
                    # which is more informative (shows every conflicting
                    # event, not just the first). To preserve the
                    # "one conflict per category" behavior of the
                    # original, take only the FIRST rival + FIRST player
                    # conflict and skip the rest.
                    if conflicts:
                        first_rival = next(
                            (c for c in conflicts
                             if "counter-programming" in c), None)
                        first_own = next(
                            (c for c in conflicts
                             if "short turnaround" in c), None)
                        conflicts = [c for c in [first_rival, first_own] if c]

                days.append({
                    "day": d,
                    "date": date_str,
                    "weekday": (date_dt.weekday()),  # 0=Mon .. 6=Sun
                    "is_today": is_today,
                    "is_past": is_past,
                    "is_future": is_future,
                    "min_lead_time_blocked": min_lead_blocked,
                    "is_eligible": is_eligible,
                    "player_events": player_events,
                    "rival_events": rival_events,
                    "conflicts": conflicts,
                    "has_conflict": len(conflicts) > 0,
                })

            return {
                "ok": True,
                "current_date": sim_date_str,
                "month": m_,
                "year": y_,
                "month_name": month_name,
                "prev_month": {"month": prev_m, "year": prev_y},
                "next_month": {"month": next_m, "year": next_y},
                "player_promo_id": pid,
                "player_promo_name": player_promo_name,
                "min_lead_days": 14,
                "first_weekday": first_weekday,
                "days": days,
            }
        except Exception as e:
            print(f"[api.get_calendar_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_date_conflicts(self, event_date):
        """Return conflict warnings for a single date (event_builder date picker).

        Lightweight single-date check — used by the Stack a Card screen's
        date picker to warn the player when their chosen date collides
        with a rival event (±2 days) or one of their own events (7 days).

        Per docs/MASTER_PLAN_MATCHMAKING_V2.md §2.2 + §2.3.

        Args:
          event_date: str "YYYY-MM-DD"

        Returns:
          {
            "ok": true,
            "date": "2027-03-15",
            "min_lead_days": 14,
            "is_past": false,
            "min_lead_time_blocked": false,
            "is_eligible": true,
            "conflicts": [
              {"kind": "rival", "promo_name": "...", "event_name": "...",
               "delta_days": 2, "weekday": "Sat", "phrase": "..."},
              {"kind": "own", "event_name": "...",
               "delta_days": 5, "weekday": "Fri", "phrase": "..."}
            ],
            "voice": "Clear date" | "Counter-programming risk" | "Short turnaround"
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            if not event_date:
                return {"ok": False, "error": "No date supplied."}
            try:
                target_dt = datetime.strptime(event_date, "%Y-%m-%d")
            except (ValueError, TypeError):
                return {"ok": False, "error": "Invalid date format (use YYYY-MM-DD)."}
            conn = self.conn

            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            try:
                sim_dt = datetime.strptime(sim_date_str, "%Y-%m-%d") if sim_date_str else None
            except (ValueError, TypeError):
                sim_dt = None

            is_past = False
            min_lead_blocked = False
            if sim_dt:
                if target_dt.date() < sim_dt.date():
                    is_past = True
                elif target_dt.date() >= sim_dt.date():
                    delta_days = (target_dt.date() - sim_dt.date()).days
                    if delta_days < 14:
                        min_lead_blocked = True
            is_eligible = (sim_dt is None) or (
                target_dt.date() > sim_dt.date() and not min_lead_blocked
            )

            # ±7-day window (covers both rival ±2 and own ±7).
            window_start = (target_dt - timedelta(days=7)).strftime("%Y-%m-%d")
            window_end = (target_dt + timedelta(days=8)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT e.event_id, e.event_name, e.event_date, e.promotion_id, p.name "
                "FROM events e "
                "LEFT JOIN promotions p ON p.promotion_id = e.promotion_id "
                "WHERE e.event_date >= ? AND e.event_date < ? "
                "  AND e.status IN ('scheduled', 'card_confirmed') "
                "ORDER BY ABS(julianday(e.event_date) - julianday(?)) ASC",
                (window_start, window_end, event_date),
            ).fetchall()

            conflicts = []
            for r in rows:
                (_eid, ename, edate, epromo, pname) = r
                if edate == event_date:
                    continue
                try:
                    e_dt = datetime.strptime(edate, "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                delta = abs((e_dt - target_dt).days)
                weekday = e_dt.strftime("%a")
                if epromo == pid and delta <= 7:
                    conflicts.append({
                        "kind": "own",
                        "event_name": ename or "",
                        "delta_days": delta,
                        "weekday": weekday,
                        "phrase": (f"You're already running '{ename or 'your event'}' "
                                   f"on {weekday} — short turnaround."),
                    })
                elif epromo != pid and delta <= 2:
                    conflicts.append({
                        "kind": "rival",
                        "promo_name": pname or "Rival",
                        "event_name": ename or "",
                        "delta_days": delta,
                        "weekday": weekday,
                        "phrase": (f"{pname or 'Rival'} is running "
                                   f"'{ename or 'their event'}' on {weekday} — "
                                   f"counter-programming will split the gate."),
                    })

            # Voice: priority = rival > own > clear.
            if any(c["kind"] == "rival" for c in conflicts):
                voice = "Counter-programming risk"
            elif any(c["kind"] == "own" for c in conflicts):
                voice = "Short turnaround"
            else:
                voice = "Clear date"

            return {
                "ok": True,
                "date": event_date,
                "current_date": sim_date_str,
                "min_lead_days": 14,
                "is_past": is_past,
                "min_lead_time_blocked": min_lead_blocked,
                "is_eligible": is_eligible,
                "conflicts": conflicts,
                "voice": voice,
            }
        except Exception as e:
            print(f"[api.get_date_conflicts] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # PHASE M4 — MATCHMAKING SCREEN API
    # Per docs/MASTER_PLAN_MATCHMAKING.md §1.2 (the 3-column layout).
    # ============================================================

    def get_matchmaking_data(self, event_id):
        """Return everything the Matchmaking screen needs to render.

        Per docs/MASTER_PLAN_MATCHMAKING.md §"Backend changes":
          - event info (venue, levers, name, date)
          - eligible fighters (player's roster, filtered)
          - currently booked fights (with matchup scores + punditry
            analysis pre-computed for the chip + voice phrases)

        Args:
          event_id: int — the event whose card to load.

        Returns:
          {
            ok: True,
            event: {id, name, date, venue, levers...},
            promo: {...same shape as get_event_builder_data},
            eligible_fighters: [{fighter_id, name, nickname,
                                  wc_name, ranking, record_str,
                                  momentum_short, has_portrait, ...}],
            booked_fights: [{fight_id, card_slot, card_position,
                              red_fighter, blue_fighter, matchup_score,
                              matchup_phrase, matchup_color, is_title_fight,
                              analysis, ...}],
            card_preview: {card_draw, card_draw_score, card_draw_phrase,
                            card_health_flags, n_fights_booked},
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            eid = int(event_id or 0)
            if not eid:
                return {"ok": False,
                        "error": "No event selected. Go to Stack a Card to create one first."}

            # --- event row + venue + levers ---
            ev_row = conn.execute(
                "SELECT e.event_id, e.event_name, e.event_date, "
                "e.venue_id, e.market_id, e.ticket_price, "
                "e.marketing_spend, e.ppv_price, e.is_ppv, e.status, "
                "v.name, v.capacity, v.venue_type, "
                "c.name, n.name, m.heat_level, "
                "p.reputation, p.fan_trust, p.broadcast_tier, "
                "p.current_cash, p.size_tier, p.name "
                "FROM events e "
                "JOIN venues v ON v.venue_id=e.venue_id "
                "JOIN markets m ON m.market_id=e.market_id "
                "JOIN cities c ON c.city_id=v.city_id "
                "LEFT JOIN nations n ON n.nation_id=c.nation_id "
                "JOIN promotions p ON p.promotion_id=e.promotion_id "
                "WHERE e.event_id=? AND e.promotion_id=?",
                (eid, pid),
            ).fetchone()
            if not ev_row:
                return {"ok": False,
                        "error": "Event not found. Go to Stack a Card to create one first."}
            (eid2, ev_name, ev_date, venue_id, _market_id,
             ticket_price, marketing_spend, ppv_price, is_ppv, status,
             venue_name, venue_cap, venue_type,
             city_name, nation_name, market_heat,
             promo_rep, promo_trust, broadcast_tier,
             current_cash, size_tier, promo_name) = ev_row
            event_info = {
                "event_id": eid2,
                "event_name": ev_name,
                "event_date": ev_date,
                "venue_id": venue_id,
                "venue_name": venue_name,
                "venue_capacity": venue_cap,
                "venue_type": venue_type,
                "city_name": city_name,
                "nation_name": nation_name,
                "ticket_price": ticket_price,
                "marketing_spend": marketing_spend,
                "ppv_price": ppv_price,
                "is_ppv": bool(is_ppv),
                "status": status,
            }
            promo_info = {
                "id": pid,
                "name": promo_name,
                "current_cash": float(current_cash or 0),
                "cash_display": _format_cash(float(current_cash or 0)),
                "is_cash_negative": (current_cash or 0) < 0,
                "reputation": promo_rep,
                "reputation_phrase": _reputation_phrase(promo_rep or 50),
                "fan_trust": promo_trust,
                "fan_trust_phrase": _fan_trust_phrase(promo_trust or 50),
                "broadcast_tier": broadcast_tier or "local_stream",
                "can_run_ppv": broadcast_tier in ("ppv_global",
                                                  "ppv_streaming"),
                "size_tier": size_tier or "small",
                "market_heat": market_heat,
                "venue_capacity": venue_cap,
            }

            # --- eligible fighters (player's roster) ---
            # Reuses services.matchmaking._get_available_fighters_for_card
            # which filters out injured, suspended, recently-fought.
            # We additionally exclude fighters already booked on THIS
            # event's card.
            # MM3.1 (docs/MASTER_PLAN_MATCHMAKING_V2.md §3.1): pass
            # event_id so the cross-event ±7-day booking exclusion
            # fires (a fighter already booked on another scheduled
            # event within ±7 days of THIS event's date is excluded).
            try:
                from services.matchmaking import (
                    _get_available_fighters_for_card,
                )
                clock = get_clock(conn)
                event_date_str = ev_date or (clock[0] if clock else None)
                available = _get_available_fighters_for_card(
                    conn, pid, before_date=event_date_str,
                    event_id=eid,
                )
            except Exception as e:
                print(f"[api.get_matchmaking_data] available fighters: {e}",
                      flush=True)
                available = []
                clock = get_clock(conn)
            sim_date_for_age = clock[0] if clock else None

            # Get the set of fighter_ids already booked on this card so
            # we exclude them from the eligible list.
            booked_ids_row = conn.execute(
                "SELECT DISTINCT fp.fighter_id "
                "FROM fights f "
                "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
                "WHERE f.event_id=?",
                (eid,),
            ).fetchall()
            booked_ids = set(r[0] for r in booked_ids_row if r[0])

            # MM3.2 — Build a {fighter_id: camp_status} lookup from the
            # available-fighters list so _fighter_brief can include the
            # camp_status chip on each roster row.
            camp_status_by_fid = {
                f['fighter_id']: f.get('camp_status', 'ready')
                for f in available
            }

            # Phase 6 / Task B2 — batched brief lookup (was: per-fighter
            # call to _fighter_brief → 4+ subqueries each → 400+ queries
            # for a 100-fighter roster). _fighter_briefs_batched runs
            # 4 queries total (main JOIN, rank window, recent_form
            # window, titles JOIN) and returns a {fid: brief} map.
            eligible_ids = [
                f['fighter_id'] for f in available
                if f['fighter_id'] not in booked_ids
            ]
            briefs_by_fid = self._fighter_briefs_batched(
                conn, eligible_ids, sim_date=sim_date_for_age,
            )
            eligible = []
            for fid in eligible_ids:
                info = briefs_by_fid.get(fid)
                if info:
                    # MM3.2 — attach camp_status to the brief so the
                    # JS roster browser can render the chip.
                    info['camp_status'] = camp_status_by_fid.get(
                        fid, 'ready',
                    )
                    eligible.append(info)

            # --- currently booked fights ---
            booked_fights = self._get_booked_fights_for_event(conn, eid)

            # --- card preview (real card_draw + health flags) ---
            try:
                card_preview = _project_card_draw(conn, eid)
            except Exception as e:
                print(f"[api.get_matchmaking_data] preview: {e}", flush=True)
                card_preview = {
                    "card_draw": 1.0, "card_draw_score": 0,
                    "card_draw_phrase": "This card has no pulse.",
                    "card_health_flags": [], "n_fights": 0,
                    "me_marketability": 0, "co_marketability": 0,
                    "n_title_fights": 0, "n_rivalry_fights": 0,
                    "avg_card_marketability": 0,
                }

            # MM1.4 — card_confirmed flag: True when the card is locked
            # (status='card_confirmed' OR legacy scheduled-with-fights
            # for backward compat). When True, the projection is shown;
            # when False, the projection is hidden ("Confirm card to see
            # projected revenue" placeholder).
            card_confirmed = (
                status == 'card_confirmed'
                or (status == 'scheduled' and len(booked_fights) > 0)
            )

            return {
                "ok": True,
                "event": event_info,
                "promo": promo_info,
                "eligible_fighters": eligible,
                "booked_fights": booked_fights,
                "card_preview": card_preview,
                "card_confirmed": card_confirmed,
            }
        except Exception as e:
            print(f"[api.get_matchmaking_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_rivalry_partners(self, fighter_id):
        """Return all fighters with an active rivalry (heat ≥ 50) with
        the given fighter.

        Per MM1.2 #8: the JS uses this when the Red Corner is picked to
        flag eligible Blue Corner fighters who have a rivalry with the
        Red Corner — so the player can see ⚔ icons next to fighters
        with bad blood before picking them.

        Returns:
          {ok, partner_ids: [{fighter_id, heat, type, label}, ...]}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            fid = int(fighter_id or 0)
            if not fid:
                return {"ok": False, "error": "Missing fighter_id."}
            rows = conn.execute(
                "SELECT fighter_a_id, fighter_b_id, rivalry_heat, "
                "rivalry_type, fights_count, fighter_a_wins, "
                "fighter_b_wins, draws "
                "FROM rivalries "
                "WHERE is_active=1 AND "
                "(fighter_a_id=? OR fighter_b_id=?) AND rivalry_heat >= 50 "
                "ORDER BY rivalry_heat DESC",
                (fid, fid),
            ).fetchall()
            partners = []
            for (a_id, b_id, heat, rtype, n_fights, a_wins, b_wins,
                 draws) in rows:
                partner_id = b_id if a_id == fid else a_id
                label = _rivalry_type_label(
                    rtype, int(heat or 0), int(n_fights or 0),
                    int(a_wins or 0), int(b_wins or 0), int(draws or 0),
                )
                partners.append({
                    "fighter_id": partner_id,
                    "heat": int(heat or 0),
                    "type": rtype or "",
                    "label": label,
                })
            return {"ok": True, "partner_ids": partners,
                    "fighter_id": fid}
        except Exception as e:
            print(f"[api.get_rivalry_partners] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # P5.1 — Booking Adviser (suggested matchups)
    # ============================================================
    # Per docs/P5_P6_PLAN.md §2.P5.1: surface opportunities the player
    # might miss — NOT auto-booking. Each suggestion is one matchup
    # with a reason chip + quality phrase. The player clicks a row
    # to fill the Red/Blue corners (they still have to hit "Add to
    # Card" themselves).
    #
    # Sources (in priority order — first match wins, no fighter
    # appears twice across the suggestion list):
    #   1. Hometown  — fighter.birth_nation_id matches the event
    #      venue's nation. (Voice: "Hometown")
    #   2. Title Contender — top-2 ranked fighters in a WC who
    #      haven't fought each other. (Voice: "Title Contender")
    #   3. Bad Blood — fighters with active rivalries, heat >= 50.
    #      (Voice: "Bad Blood")
    #   4. Debut — fighters with 0 fights, age <= 25. (Voice: "Debut")
    #   5. Hot Streak — 2 fighters on 3+ win streaks in same WC.
    #      (Voice: "Hot Streak")
    #
    # Returns 3-5 suggestions. Each suggestion carries the FULL
    # fighter brief for both corners (so the JS can render the same
    # portrait + chips + record_str as the roster browser) plus a
    # reason_chip string + reason_phrase (voice) + quality_phrase
    # (voice — derived from the matchup analysis if available).

    def get_suggested_matchups(self, event_id):
        """Return 3-5 suggested matchups for the Booking Adviser panel.

        Args:
          event_id: int — the event whose card we're building.

        Returns:
          {ok, event_id, suggestions: [
            {red_fighter: brief, blue_fighter: brief,
             reason_chip: "Hometown"|"Title Contender"|"Bad Blood"|
                          "Debut"|"Hot Streak",
             reason_phrase: str (voice),
             quality_phrase: str (voice)},
            ...
          ]}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            eid = int(event_id or 0)
            if not eid:
                return {"ok": False,
                        "error": "No event selected. Go to Stack a Card to create one first."}

            # Fetch event venue nation (for hometown suggestions).
            ev_row = conn.execute(
                "SELECT e.event_id, e.event_date, e.venue_id, "
                "n.nation_id, n.name "
                "FROM events e "
                "JOIN venues v ON v.venue_id=e.venue_id "
                "JOIN cities c ON c.city_id=v.city_id "
                "LEFT JOIN nations n ON n.nation_id=c.nation_id "
                "WHERE e.event_id=? AND e.promotion_id=?",
                (eid, pid),
            ).fetchone()
            if not ev_row:
                return {"ok": False,
                        "error": "Event not found. Go to Stack a Card to create one first."}
            (eid2, ev_date, _venue_id, nation_id, nation_name) = ev_row

            # Get the player's eligible fighters (same filter as the
            # Matchmaking screen — injured/suspended/recently-fought
            # are excluded). Reuses services.matchmaking.
            try:
                from services.matchmaking import (
                    _get_available_fighters_for_card,
                )
                clock = get_clock(conn)
                event_date_str = ev_date or (clock[0] if clock else None)
                available = _get_available_fighters_for_card(
                    conn, pid, before_date=event_date_str,
                    event_id=eid,
                )
            except Exception as e:
                print(f"[api.get_suggested_matchups] available fighters: {e}",
                      flush=True)
                available = []

            # Get fighters already booked on this card — exclude from
            # suggestions (they're already on the card).
            booked_ids_row = conn.execute(
                "SELECT DISTINCT fp.fighter_id "
                "FROM fights f "
                "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
                "WHERE f.event_id=?",
                (eid,),
            ).fetchall()
            booked_ids = set(r[0] for r in booked_ids_row if r[0])

            # Build the eligible pool: fighter_id -> brief dict.
            eligible_briefs = {}
            for f in available:
                fid = f['fighter_id']
                if fid in booked_ids:
                    continue
                info = self._fighter_brief(conn, fid)
                if info:
                    info['camp_status'] = f.get('camp_status', 'ready')
                    eligible_briefs[fid] = info

            if not eligible_briefs:
                return {"ok": True, "event_id": eid, "suggestions": []}

            # Also pull hometown + debut + streak info for each eligible
            # fighter in one query (avoid N+1 inside _fighter_brief).
            elig_ids = list(eligible_briefs.keys())
            elig_placeholders = ",".join("?" * len(elig_ids))
            extra_rows = conn.execute(
                "SELECT f.fighter_id, f.birth_nation_id, "
                "n.name AS birth_nation_name, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "fc.win_streak, fc.loss_streak, "
                "f.date_of_birth "
                "FROM fighters f "
                "LEFT JOIN nations n ON n.nation_id=f.birth_nation_id "
                "LEFT JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
                f"WHERE f.fighter_id IN ({elig_placeholders})",
                elig_ids,
            ).fetchall()
            extra = {}
            for r in extra_rows:
                extra[r[0]] = {
                    "birth_nation_id": r[1],
                    "birth_nation_name": r[2],
                    "wins": r[3] or 0,
                    "losses": r[4] or 0,
                    "draws": r[5] or 0,
                    "win_streak": r[6] or 0,
                    "loss_streak": r[7] or 0,
                    "total_fights": (r[3] or 0) + (r[4] or 0) + (r[5] or 0),
                    "date_of_birth": r[8],
                }

            # Compute age for the debut filter (age <= 25).
            # Reuse the sim clock.
            clock_row = conn.execute(
                "SELECT current_date FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            ref_date_str = clock_row[0] if clock_row else None
            def _age(dob_str):
                if not dob_str or not ref_date_str:
                    return None
                try:
                    from datetime import datetime as _dt
                    d = _dt.strptime(dob_str, "%Y-%m-%d")
                    r = _dt.strptime(ref_date_str, "%Y-%m-%d")
                    a = r.year - d.year
                    if (r.month, r.day) < (d.month, d.day):
                        a -= 1
                    return a
                except (ValueError, TypeError):
                    return None

            suggestions = []
            used_pairs = set()  # frozenset({red_id, blue_id}) — no duplicate pairings
            used_fighter_ids = set()  # a fighter appears in at most one suggestion

            def _try_add(red_id, blue_id, reason_chip, reason_phrase,
                         quality_phrase):
                """Add a suggestion if both fighters are eligible, not
                already used, and not already paired. Returns True if
                added."""
                if red_id == blue_id:
                    return False
                if red_id not in eligible_briefs or blue_id not in eligible_briefs:
                    return False
                if red_id in used_fighter_ids or blue_id in used_fighter_ids:
                    return False
                pair_key = frozenset((red_id, blue_id))
                if pair_key in used_pairs:
                    return False
                used_pairs.add(pair_key)
                used_fighter_ids.add(red_id)
                used_fighter_ids.add(blue_id)
                suggestions.append({
                    "red_fighter": eligible_briefs[red_id],
                    "blue_fighter": eligible_briefs[blue_id],
                    "reason_chip": reason_chip,
                    "reason_phrase": reason_phrase,
                    "quality_phrase": quality_phrase,
                })
                return True

            # ---- Source 1: Hometown (birth_nation_id == event nation) ----
            if nation_id:
                hometown_ids = [
                    fid for fid in elig_ids
                    if extra.get(fid, {}).get("birth_nation_id") == nation_id
                ]
                # Pair hometown fighters against each other (same WC +
                # same gender) — the hometown-vs-hometown angle is the
                # juiciest. If only one hometown fighter, pair them
                # against anyone in their WC.
                i = 0
                while i + 1 < len(hometown_ids) and len(suggestions) < 5:
                    a = hometown_ids[i]
                    b = hometown_ids[i + 1]
                    ba = eligible_briefs[a]
                    bb = eligible_briefs[b]
                    if (ba["weight_class_id"] == bb["weight_class_id"]
                            and ba["gender"] == bb["gender"]):
                        _try_add(
                            a, b, "Hometown",
                            f"Both fighters hail from {nation_name}. "
                            "The crowd will have a dog in this fight.",
                            "A regional pride matchup — give the home "
                            "fans something to cheer for.",
                        )
                        i += 2
                    else:
                        i += 1
                # If odd one out, pair them against any same-WC fighter.
                if i < len(hometown_ids) and len(suggestions) < 5:
                    a = hometown_ids[i]
                    ba = eligible_briefs[a]
                    for fid in elig_ids:
                        if fid == a or fid in used_fighter_ids:
                            continue
                        bb = eligible_briefs[fid]
                        if (ba["weight_class_id"] == bb["weight_class_id"]
                                and ba["gender"] == bb["gender"]):
                            _try_add(
                                a, fid, "Hometown",
                                f"{ba['name']} fights in front of a home "
                                f"crowd in {nation_name}.",
                                "Home-cage advantage is real — give the "
                                "hometown fighter a showcase.",
                            )
                            break

            # ---- Source 2: Title Contender (top-2 ranked, never fought) ----
            if len(suggestions) < 5:
                # Group eligible fighters by WC, sort by rank_num asc
                # (champion first, then #1, #2, etc.).
                wc_groups = {}
                for fid in elig_ids:
                    brief = eligible_briefs[fid]
                    wc_id = brief.get("weight_class_id")
                    if not wc_id:
                        continue
                    wc_groups.setdefault(wc_id, []).append(fid)

                for wc_id, fid_list in wc_groups.items():
                    if len(suggestions) >= 5:
                        break
                    # Sort: champions first, then by rank_num asc
                    # (rank_num=0 means unranked — push to the back).
                    def _rank_key(fid):
                        brief = eligible_briefs[fid]
                        holds_title = (
                            brief.get("title_chip", {}).get("holds_title")
                        )
                        rank_num = brief.get("rank_num", 0) or 0
                        return (0 if holds_title else 1, rank_num, fid)
                    fid_list.sort(key=_rank_key)
                    # Take the top 2 (champion + #1 contender, OR #1 + #2).
                    if len(fid_list) < 2:
                        continue
                    a, b = fid_list[0], fid_list[1]
                    ba = eligible_briefs[a]
                    bb = eligible_briefs[b]
                    # Check they haven't fought each other (query
                    # fight_history / fight_participants).
                    fought = conn.execute(
                        "SELECT COUNT(*) FROM fight_participants fp1 "
                        "JOIN fight_participants fp2 "
                        "  ON fp2.fight_id=fp1.fight_id "
                        "  AND fp2.fighter_id=? "
                        "WHERE fp1.fighter_id=?",
                        (a, b),
                    ).fetchone()
                    n_prior = int(fought[0] or 0) if fought else 0
                    if n_prior > 0:
                        continue  # already fought — skip
                    holds_title_a = ba.get("title_chip", {}).get("holds_title")
                    if holds_title_a:
                        reason_phrase = (
                            f"Champion {ba['name']} vs top contender "
                            f"{bb['name']}. A title defense the division "
                            "has been waiting for."
                        )
                        quality_phrase = (
                            "Belt on the line — divisional supremacy at stake."
                        )
                    else:
                        reason_phrase = (
                            f"{ba['name']} and {bb['name']} are the top "
                            "two ranked fighters in the division. A "
                            "number-one-contender fight in the making."
                        )
                        quality_phrase = (
                            "Top of the rankings collide — the winner "
                            "moves to the front of the title line."
                        )
                    _try_add(a, b, "Title Contender",
                             reason_phrase, quality_phrase)

            # ---- Source 3: Bad Blood (active rivalries, heat >= 50) ----
            if len(suggestions) < 5:
                riv_rows = conn.execute(
                    "SELECT fighter_a_id, fighter_b_id, rivalry_heat, "
                    "rivalry_type, fights_count, fighter_a_wins, "
                    "fighter_b_wins, draws "
                    "FROM rivalries "
                    "WHERE is_active=1 AND rivalry_heat >= 50 "
                    "ORDER BY rivalry_heat DESC "
                    "LIMIT 50",
                ).fetchall()
                for (a, b, heat, rtype, n_fights, a_wins, b_wins, draws) in riv_rows:
                    if len(suggestions) >= 5:
                        break
                    if a not in eligible_briefs or b not in eligible_briefs:
                        continue
                    # Same-WC + same-gender check (rivalries can span WCs
                    # in theory — skip if mismatched).
                    ba = eligible_briefs[a]
                    bb = eligible_briefs[b]
                    if ba["weight_class_id"] != bb["weight_class_id"]:
                        continue
                    if ba["gender"] != bb["gender"]:
                        continue
                    label = _rivalry_type_label(
                        rtype, int(heat or 0), int(n_fights or 0),
                        int(a_wins or 0), int(b_wins or 0), int(draws or 0),
                    )
                    heat_band = (
                        "boiling over" if heat >= 80 else
                        "heating up" if heat >= 65 else
                        "simmering"
                    )
                    _try_add(
                        a, b, "Bad Blood",
                        f"{label}. The rivalry is {heat_band}.",
                        "Bad blood sells — let them settle it in the cage.",
                    )

            # ---- Source 4: Debut (0 fights, age <= 25) ----
            if len(suggestions) < 5:
                debut_ids = []
                for fid in elig_ids:
                    ex = extra.get(fid, {})
                    if ex.get("total_fights", 0) != 0:
                        continue
                    age = _age(ex.get("date_of_birth"))
                    if age is not None and age <= 25:
                        debut_ids.append(fid)
                # Pair debut fighters against each other (same WC +
                # same gender) — prospect-vs-prospect is the juiciest.
                i = 0
                while i + 1 < len(debut_ids) and len(suggestions) < 5:
                    a = debut_ids[i]
                    b = debut_ids[i + 1]
                    ba = eligible_briefs[a]
                    bb = eligible_briefs[b]
                    if (ba["weight_class_id"] == bb["weight_class_id"]
                            and ba["gender"] == bb["gender"]):
                        _try_add(
                            a, b, "Debut",
                            f"Two unbeaten prospects — {ba['name']} and "
                            f"{bb['name']} — making their walk for the "
                            "first time.",
                            "A prospect showcase — the future of the "
                            "division starts here.",
                        )
                        i += 2
                    else:
                        i += 1

            # ---- Source 5: Hot Streak (2 fighters on 3+ win streaks, same WC) ----
            if len(suggestions) < 5:
                streak_ids = [
                    fid for fid in elig_ids
                    if extra.get(fid, {}).get("win_streak", 0) >= 3
                ]
                # Pair streak-fighters against each other (same WC +
                # same gender). Win-streak-vs-win-streak is electric.
                i = 0
                while i + 1 < len(streak_ids) and len(suggestions) < 5:
                    a = streak_ids[i]
                    b = streak_ids[i + 1]
                    ba = eligible_briefs[a]
                    bb = eligible_briefs[b]
                    if (ba["weight_class_id"] == bb["weight_class_id"]
                            and ba["gender"] == bb["gender"]):
                        sa = extra[a]["win_streak"]
                        sb = extra[b]["win_streak"]
                        _try_add(
                            a, b, "Hot Streak",
                            f"{ba['name']} is on a {sa}-fight win streak. "
                            f"{bb['name']} has won {sb} straight. "
                            "Something has to give.",
                            "Momentum vs momentum — the winner keeps "
                            "climbing, the loser resets.",
                        )
                        i += 2
                    else:
                        i += 1

            # Cap at 5 (the spec asks for 3-5). If we somehow got
            # more, trim. If we got fewer, that's fine — the panel
            # shows "N suggestions" and renders what we have.
            suggestions = suggestions[:5]

            return {
                "ok": True,
                "event_id": eid,
                "suggestions": suggestions,
                "nation_name": nation_name,
            }
        except Exception as e:
            print(f"[api.get_suggested_matchups] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # P1-WIRE-4-SCREENS — Bad Blood (Rivalries) screen
    # ============================================================
    # Per docs/P1_PLAN_WIRE_SCREENS.md §1 + docs/REVIEW_P1_SCREEN_BACKENDS.md
    # §2: paginated, filterable list of all rivalries in the world.
    # Backed by src/rivalries.py (1053 LOC) — the table already
    # exists (390 rows / 286 active) and is populated by event-bus
    # subscribers on fight resolution + title changes + social posts.
    # This method is purely a reader — it joins fighters for names
    # + fighter_career for career-stage descriptors + computes a
    # voice-layer heat phrase per CONVENTIONS §14.
    # ------------------------------------------------------------

    def get_rivalries_data(self, page=1, filters=None):
        """Return paginated rivalries for the Bad Blood screen.

        Args:
          page:    int page number (20 rivalries per page)
          filters: {
            "type":       one of VALID_RIVALRY_TYPES or "all",
            "heat_band":  "cold" (0-19) | "simmering" (20-39) |
                          "warm" (40-59) | "hot" (60-79) |
                          "boiling" (80-100) | "all",
            "scope":      "all" (every rivalry) |
                          "player_promo" (at least one fighter on
                          player's promo) |
                          "involves_my_roster" (at least one fighter
                          on player's roster),
            "search":     substring on fighter names
          }

        Returns:
          {
            "rivalries": [
              {
                "rivalry_id", "rivalry_heat", "rivalry_type",
                "type_label", "heat_phrase",
                "fights_count", "fighter_a_wins", "fighter_b_wins",
                "draws", "head_to_head",
                "origin_description",
                "last_escalation_date", "is_active",
                "fighter_a": {id, name, nickname, career_stage},
                "fighter_b": {id, name, nickname, career_stage}
              }, ...
            ],
            "active_count", "dormant_count", "boiling_count",
            "title_rivalry_count",
            "by_type":     [{type, label, count, avg_heat}, ...],
            "page", "per_page": 20, "total", "total_pages", "filters"
          }

        Voice compliance — CONVENTIONS §17.4 "Rich Not Thin" carve-out
        (Phase 7 / Task A8):
          * ``rivalry_heat`` (raw 0-100 int) is KEPT in the JSON ONLY
            as the bar-width percentage for the heat meter in
            ``rivalries.js:229`` (``heatPct``). Per §17.4, visualization
            widths are an explicit carve-out — the polygon / bar fill
            conveys relative magnitude without leaking the underlying
            rating as a displayed number.
          * Text display uses ``heat_phrase`` ONLY ("BOILING OVER",
            "READY TO EXPLODE", etc. — already voice-layered via
            ``_rivalry_heat_phrase()``). Phase 6 B6 removed the raw-int
            text display (the old "BOILING OVER · 92" format); only the
            phrase survives in the rendered card.
          * The raw int is NOT shown as text anywhere in the UI.
        """
        try:
            pid = self.get_player_promotion()
            conn = self.conn
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 20

            # ---- Build WHERE clause ----
            where_parts = []
            params = []

            rtype_filter = (filters.get("type") or "").strip()
            if rtype_filter and rtype_filter != "all":
                where_parts.append("r.rivalry_type = ?")
                params.append(rtype_filter)

            heat_band = (filters.get("heat_band") or "").strip()
            if heat_band and heat_band != "all":
                band_map = {
                    "cold":      (0, 19),
                    "simmering": (20, 39),
                    "warm":      (40, 59),
                    "hot":       (60, 79),
                    "boiling":   (80, 100),
                }
                band = band_map.get(heat_band)
                if band:
                    where_parts.append(
                        "r.rivalry_heat BETWEEN ? AND ?")
                    params.extend([band[0], band[1]])

            scope = (filters.get("scope") or "").strip()
            if scope == "player_promo" and pid:
                where_parts.append(
                    "(fa.current_promotion_id = ? OR "
                    " fb.current_promotion_id = ?)")
                params.extend([pid, pid])
            elif scope == "involves_my_roster" and pid:
                where_parts.append(
                    "(fa.current_promotion_id = ? OR "
                    " fb.current_promotion_id = ?)")
                params.extend([pid, pid])

            search = (filters.get("search") or "").strip()
            if search:
                where_parts.append(
                    "(fa.first_name LIKE ? OR fa.last_name LIKE ? OR "
                    "fb.first_name LIKE ? OR fb.last_name LIKE ? OR "
                    "(fa.first_name || ' ' || fa.last_name) LIKE ? OR "
                    "(fb.first_name || ' ' || fb.last_name) LIKE ?)")
                like = f"%{search}%"
                params.extend([like, like, like, like, like, like])

            where_sql = (" WHERE " + " AND ".join(where_parts)) \
                if where_parts else ""

            # ---- Total count ----
            count_sql = (
                "SELECT COUNT(*) FROM rivalries r "
                "JOIN fighters fa ON fa.fighter_id = r.fighter_a_id "
                "JOIN fighters fb ON fb.fighter_id = r.fighter_b_id "
                + where_sql
            )
            total = int(conn.execute(count_sql, params).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page

            # ---- Page rows: sorted by heat DESC, then fights_count DESC ----
            rows_sql = (
                "SELECT r.rivalry_id, r.fighter_a_id, r.fighter_b_id, "
                "  r.rivalry_heat, r.rivalry_type, r.origin_event, "
                "  r.origin_description, r.fights_count, "
                "  r.fighter_a_wins, r.fighter_b_wins, r.draws, "
                "  r.is_active, r.last_escalation_date, r.created_at, "
                "  r.updated_at, "
                "  fa.first_name, fa.last_name, fa.nickname, "
                "  fb.first_name, fb.last_name, fb.nickname "
                "FROM rivalries r "
                "JOIN fighters fa ON fa.fighter_id = r.fighter_a_id "
                "JOIN fighters fb ON fb.fighter_id = r.fighter_b_id "
                + where_sql +
                " ORDER BY r.rivalry_heat DESC, r.fights_count DESC, "
                "  r.rivalry_id ASC "
                "LIMIT ? OFFSET ?"
            )
            rows = conn.execute(rows_sql, params + [per_page, offset]).fetchall()

            rivalries = []
            for r in rows:
                (rid, a_id, b_id, heat, rtype, origin_event,
                 origin_desc, n_fights, a_wins, b_wins, draws,
                 is_active, last_esc, created_at, updated_at,
                 a_fn, a_ln, a_nick, b_fn, b_ln, b_nick) = r
                heat = int(heat or 0)
                # Head-to-head record "W-L-D" — career stats are OK
                # per CONVENTIONS §14 carve-out.
                if (draws or 0) > 0:
                    h2h = f"{a_wins or 0}-{b_wins or 0}-{draws or 0}"
                else:
                    h2h = f"{a_wins or 0}-{b_wins or 0}"
                a_name = f"{a_fn or ''} {a_ln or ''}".strip() or "—"
                b_name = f"{b_fn or ''} {b_ln or ''}".strip() or "—"
                rivalries.append({
                    "rivalry_id": rid,
                    "rivalry_heat": heat,
                    "rivalry_type": rtype or "",
                    "type_label": _rivalry_type_pretty(rtype),
                    "heat_phrase": _rivalry_heat_phrase(heat),
                    "fights_count": int(n_fights or 0),
                    "fighter_a_wins": int(a_wins or 0),
                    "fighter_b_wins": int(b_wins or 0),
                    "draws": int(draws or 0),
                    "head_to_head": h2h,
                    "origin_description": origin_desc or "",
                    "origin_event": origin_event or "",
                    "last_escalation_date": last_esc or "",
                    "is_active": bool(is_active),
                    "created_at": created_at or "",
                    "updated_at": updated_at or "",
                    "fighter_a": {
                        "id": a_id,
                        "name": a_name,
                        "nickname": a_nick or "",
                        "career_stage": _rivalry_fighter_stage(conn, a_id),
                    },
                    "fighter_b": {
                        "id": b_id,
                        "name": b_name,
                        "nickname": b_nick or "",
                        "career_stage": _rivalry_fighter_stage(conn, b_id),
                    },
                })

            # ---- Summary stats (always full-table, not page-scoped) ----
            summary = conn.execute(
                "SELECT "
                "  SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END), "
                "  SUM(CASE WHEN is_active=0 THEN 1 ELSE 0 END), "
                "  SUM(CASE WHEN rivalry_heat >= 80 THEN 1 ELSE 0 END), "
                "  SUM(CASE WHEN rivalry_type='title_rivalry' THEN 1 "
                "           ELSE 0 END) "
                "FROM rivalries"
            ).fetchone()
            active_count = int(summary[0] or 0)
            dormant_count = int(summary[1] or 0)
            boiling_count = int(summary[2] or 0)
            title_rivalry_count = int(summary[3] or 0)

            # Breakdown by type — for the filter dropdown counts.
            type_rows = conn.execute(
                "SELECT rivalry_type, COUNT(*), ROUND(AVG(rivalry_heat),1) "
                "FROM rivalries GROUP BY rivalry_type "
                "ORDER BY 2 DESC"
            ).fetchall()
            by_type = [
                {"type": t or "",
                 "label": _rivalry_type_pretty(t),
                 "count": int(c or 0),
                 "avg_heat": float(h or 0)}
                for (t, c, h) in type_rows
            ]

            return {
                "rivalries": rivalries,
                "active_count": active_count,
                "dormant_count": dormant_count,
                "boiling_count": boiling_count,
                "title_rivalry_count": title_rivalry_count,
                "by_type": by_type,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "filters": {
                    "type": rtype_filter or "all",
                    "heat_band": heat_band or "all",
                    "scope": scope or "all",
                    "search": search,
                },
            }
        except Exception as e:
            print(f"[api.get_rivalries_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"rivalries": [], "active_count": 0, "dormant_count": 0,
                    "boiling_count": 0, "title_rivalry_count": 0,
                    "by_type": [], "page": 1, "per_page": 20,
                    "total": 0, "total_pages": 1, "filters": {},
                    "error": str(e)}

    def _fighter_briefs_batched(self, conn, fighter_ids, sim_date=None):
        """Return {fighter_id: brief_dict} for a batch of fighters.

        Phase 6 / Task B2 — replaces the N+1 pattern where
        ``get_matchmaking_data`` called ``_fighter_brief`` per fighter
        (4+ subqueries each → 400+ queries for a 100-fighter roster).
        This batched helper runs 4 queries total:

          1. Main brief — fighters JOINed to weight_classes +
             fighter_career + fighter_descriptors + rankings +
             style_archetypes.
          2. Rank — ``RANK() OVER (PARTITION BY weight_class_id,
             promotion_id ORDER BY rating DESC, fighter_id ASC)`` so
             each fighter's #1-15 (or Unranked) is computed in one
             window-function pass.
          3. Recent form — ``ROW_NUMBER() OVER (PARTITION BY
             fighter_id ORDER BY fight_history_id DESC)`` filtered to
             rn <= 5 so we get the last 5 fights per fighter in one
             query (was: per-fighter ``ORDER BY fight_history_id DESC
             LIMIT 5``).
          4. Titles — single JOIN to titles (is_vacant=0) for the
             batch — was per-fighter query.

        The returned brief dicts have the SAME shape as
        ``_fighter_brief()`` so the JS layer (matchmaking.js) requires
        no changes.

        Args:
          fighter_ids: list of ints (eligible fighter_ids). Empty list
                       is OK — returns ``{}``.
          sim_date:    str YYYY-MM-DD (from get_clock — fetched ONCE
                       by the caller, not per fighter). When None,
                       age computation is skipped (``age=None``).

        Returns:
          ``{fighter_id: brief_dict}`` — missing fighter_ids are
          simply absent from the dict (caller treats missing as
          "skip this fighter", same as ``_fighter_brief`` returning
          None).
        """
        if not fighter_ids:
            return {}
        if not sim_date:
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None

        placeholders = ",".join("?" * len(fighter_ids))
        params = list(fighter_ids)

        # --- (1) Main brief fields (single JOINed query) ---
        main_rows = conn.execute(
            "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
            "f.weight_class_id, f.gender, f.marketability, "
            "f.height_cm, f.reach_cm, f.stance, f.portrait_path, "
            "f.date_of_birth, "
            "wc.name AS wc_name, "
            "fc.record_wins, fc.record_losses, fc.record_draws, "
            "fc.win_streak, fc.loss_streak, "
            "fd.career_phase_short, fd.momentum_short, "
            "r.rating, r.wins AS r_wins, r.losses AS r_losses, "
            "sa.name AS style_archetype_name "
            "FROM fighters f "
            "LEFT JOIN weight_classes wc "
            "  ON wc.weight_class_id = f.weight_class_id "
            "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
            "LEFT JOIN fighter_descriptors fd "
            "  ON fd.fighter_id = f.fighter_id "
            "LEFT JOIN rankings r "
            "  ON r.fighter_id = f.fighter_id "
            "  AND r.weight_class_id = f.weight_class_id "
            "  AND r.promotion_id = f.current_promotion_id "
            "LEFT JOIN style_archetypes sa "
            "  ON sa.style_archetype_id = f.fight_style_archetype_id "
            f"WHERE f.fighter_id IN ({placeholders})",
            params,
        ).fetchall()

        # --- (2) Rank via window function (single query) ---
        # RANK() OVER (PARTITION BY weight_class_id, promotion_id
        # ORDER BY rating DESC, fighter_id ASC) — matches the
        # ORDER BY used in get_rankings_data (P4.2 tiebreaker).
        #
        # IMPORTANT: we must compute the rank over the FULL partition
        # (all rankings rows sharing the fighter's WC + promo), NOT
        # just the eligible fighters. The WHERE clause inside the
        # subquery selects rankings rows whose (weight_class_id,
        # promotion_id) match the eligible fighters' (WC, promo) —
        # then the outer filter keeps only the eligible fighters'
        # rank rows. (Mirrors the OLD _fighter_brief's "COUNT(*)
        # FROM rankings r2 WHERE r2.weight_class_id=? AND
        # r2.promotion_id=? AND r2.rating > ?" semantics.)
        rank_rows = conn.execute(
            "SELECT fighter_id, rank_num FROM ("
            "  SELECT r.fighter_id, "
            "    RANK() OVER (PARTITION BY r.weight_class_id, "
            "                 r.promotion_id "
            "                 ORDER BY r.rating DESC, "
            "                 r.fighter_id ASC) AS rank_num "
            "  FROM rankings r "
            "  WHERE (r.weight_class_id, r.promotion_id) IN ("
            "    SELECT f.weight_class_id, f.current_promotion_id "
            "    FROM fighters f "
            f"    WHERE f.fighter_id IN ({placeholders})"
            "  )"
            f") WHERE fighter_id IN ({placeholders})",
            params + params,
        ).fetchall()
        rank_by_fid = {int(fid): int(rn) for (fid, rn) in rank_rows}

        # --- (3) Recent form (last 5 fights per fighter, single query) ---
        form_rows = conn.execute(
            "SELECT fighter_id, outcome, result_type, "
            "finish_round, event_date FROM ("
            "  SELECT fh.fighter_id, fh.outcome, fh.result_type, "
            "    fh.finish_round, fh.event_date, "
            "    ROW_NUMBER() OVER (PARTITION BY fh.fighter_id "
            "                       ORDER BY fh.fight_history_id DESC) AS rn "
            f"  FROM fight_history fh "
            f"  WHERE fh.fighter_id IN ({placeholders})"
            ") WHERE rn <= 5",
            params,
        ).fetchall()
        # Group per fighter; fight_history_id DESC means newest first —
        # we reverse per-fighter so oldest is leftmost (matches
        # _recent_form's WMMA5 convention).
        form_by_fid = {fid: [] for fid in fighter_ids}
        for (fid, outcome, rtype, rnd, ev_date) in form_rows:
            form_by_fid.setdefault(fid, []).append({
                "outcome": outcome or "",
                "result_type": rtype or "",
                "finish_round": rnd,
                "event_date": ev_date or "",
            })
        for fid in form_by_fid:
            form_by_fid[fid].reverse()

        # --- (4) Titles (single query) ---
        # First non-vacant title per fighter (matches _title_chip's
        # "ORDER BY title_id ASC LIMIT 1" behavior).
        title_rows = conn.execute(
            "SELECT t.current_champion_fighter_id, t.weight_class_id, "
            "wc.name "
            "FROM titles t "
            "JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id "
            f"WHERE t.is_vacant=0 "
            f"  AND t.current_champion_fighter_id IN ({placeholders}) "
            "ORDER BY t.title_id ASC",
            params,
        ).fetchall()
        title_by_fid = {}  # fid -> {weight_class_id, weight_class_name}
        for (fid, wc_id, wc_name) in title_rows:
            # Surface the first non-vacant title per fighter.
            if fid not in title_by_fid:
                title_by_fid[fid] = {
                    "weight_class_id": wc_id,
                    "weight_class_name": wc_name,
                }

        # --- Assemble brief dicts (in-memory, no further SQL) ---
        briefs = {}
        for row in main_rows:
            (fid2, fn, ln, nick, wc_id, gender, mkt,
             height_cm, reach_cm, stance, portrait_path,
             dob, wc_name,
             cwins, closses, cdraws, ws, ls,
             stage_short, mom_short, rating, r_wins, r_losses,
             style_archetype_name) = row
            w = cwins or 0; l = closses or 0; d = cdraws or 0
            record_str = f"{w}-{l}" + (f"-{d}" if d else "")
            # Rank within WC (1-15 → #N, else 0/"Unranked").
            rank_int = rank_by_fid.get(fid2, 0)
            rank_num = rank_int if 1 <= rank_int <= 15 else 0
            rank_str = f"#{rank_int}" if 1 <= rank_int <= 15 else "Unranked"
            # Streak phrase (matches _fighter_brief's logic verbatim).
            if ws and ws >= 3:
                streak_phrase = f"{ws}-fight win streak"
            elif ls and ls >= 3:
                streak_phrase = f"{ls}-fight skid"
            elif ws and ws >= 1:
                streak_phrase = f"won {ws} straight"
            elif ls and ls >= 1:
                streak_phrase = f"dropped {ls} in a row"
            else:
                streak_phrase = ""
            # Age (computed from the once-fetched sim_date — was:
            # per-fighter simulation_clock query).
            age = None
            if dob and sim_date:
                try:
                    dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                    ref_dt = datetime.strptime(sim_date, "%Y-%m-%d")
                    age = ref_dt.year - dob_dt.year
                    if (ref_dt.month, ref_dt.day) < (dob_dt.month, dob_dt.day):
                        age -= 1
                except (ValueError, TypeError):
                    pass
            # Title chip (matches _title_chip's shape).
            title_info = title_by_fid.get(fid2)
            if title_info:
                short = _short_wc(title_info["weight_class_name"])
                title_chip = {
                    "holds_title": True,
                    "title_label": f"{short} Champion",
                    "weight_class_name": title_info["weight_class_name"],
                    "weight_class_id": title_info["weight_class_id"],
                }
            else:
                title_chip = {"holds_title": False, "title_label": "—",
                              "weight_class_name": None,
                              "weight_class_id": None}
            champion_tier = "champion" if title_chip["holds_title"] else (
                "top5" if 1 <= rank_num <= 5 else "steel")
            # Recent form — convert raw rows to the block shape with
            # letter + outcome + result_type + finish_round + event_date.
            raw_form = form_by_fid.get(fid2, [])
            recent_form = []
            for fr in raw_form:
                outcome = fr.get("outcome", "")
                letter = 'W' if outcome == 'win' else (
                    'L' if outcome == 'loss' else (
                        'D' if outcome == 'draw' else 'N'))
                recent_form.append({
                    "letter": letter,
                    "outcome": outcome,
                    "result_type": fr.get("result_type", ""),
                    "finish_round": fr.get("finish_round"),
                    "event_date": fr.get("event_date", ""),
                })
            briefs[fid2] = {
                "fighter_id": fid2,
                "name": f"{fn} {ln}".strip(),
                "nickname": nick or "",
                "display_name": (f'{fn} "{nick}" {ln}'
                                 if nick else f"{fn} {ln}"),
                "weight_class_id": wc_id,
                "weight_class_name": wc_name or "—",
                "weight_class_short": _short_wc(wc_name),
                "gender": gender,
                "record_str": record_str,
                "wins": w, "losses": l, "draws": d,
                "win_streak": ws or 0, "loss_streak": ls or 0,
                "stage_short": _decode_label(stage_short) if stage_short else "",
                "momentum_short": _decode_label(mom_short) if mom_short else "",
                "streak_phrase": streak_phrase,
                "rank_str": rank_str,
                "rank_num": rank_num,
                "has_portrait": bool(portrait_path),
                "height_cm": height_cm,
                "reach_cm": reach_cm,
                "stance": stance or "",
                # Phase 7 / Task A2 — `marketability` raw int DROPPED
                # from the brief (per §17.4 "Rich Not Thin"). The voice
                # phrase `popularity_tier` below carries the same info
                # in voice form. (Mirrors the single-fighter
                # `_fighter_brief` change.)
                "popularity_tier": _popularity_tier(mkt),
                "momentum_label": _momentum_label(ws, ls),
                "recent_form": recent_form,
                "title_chip": title_chip,
                "champion_tier": champion_tier,
                "age": age,
                "style_archetype_name": style_archetype_name or "Balanced",
                "date_of_birth": dob,
            }
        return briefs

    def _fighter_brief(self, conn, fid):
        """Build a brief fighter dict for the roster browser.

        DEPRECATED for batched callers (Phase 6 / Task B2): the
        Matchmaking screen now uses ``_fighter_briefs_batched`` which
        runs 4 queries total instead of 4 per fighter (N+1 → constant).
        This single-fighter helper is retained for callers that need
        just one fighter's brief (e.g. ``_get_booked_fights_for_event``
        iterating over the few booked fights on a card — that loop
        stays N=number_of_booked_fights, not N=eligible_roster_size).

        Returns name + nickname + wc_name + ranking + record_str +
        momentum_short + has_portrait + weight_class_id + gender.

        MM1.2 (Matchmaking V2): also returns the 9 corner-slot fields
        the matchmaking screen needs at a glance:
          - popularity_tier (voice phrase from marketability)
          - momentum_label (arrow + color + label + streak_str)
          - recent_form (last 5 W/L/D blocks)
          - title_chip (holds_title + title_label)
          - rank_num (1-15 or 0 for unranked)
          - age (int)
          - style_archetype_name (Striker / Grappler / Wrestler / …)

        Phase 7 / Task A2 — the raw 0-100 `marketability` int has
        been DROPPED from the brief dict (per CONVENTIONS §17.4
        "Rich Not Thin": only the voice phrase `popularity_tier`
        crosses the API boundary; the raw int leaked in every brief
        despite the "internal — NEVER shown raw" comment). The
        server-side callers that need marketability for matchup
        scoring use `_build_fighter_dict_for_matchup` (which reads
        `fighters.marketability` directly from the DB) — they do
        NOT consume this brief's `marketability` field.
        """
        row = conn.execute(
            "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
            "f.weight_class_id, f.gender, f.marketability, "
            "f.height_cm, f.reach_cm, f.stance, f.portrait_path, "
            "f.date_of_birth, f.fight_style_archetype_id, "
            "wc.name, "
            "fc.record_wins, fc.record_losses, fc.record_draws, "
            "fc.win_streak, fc.loss_streak, "
            "fd.career_phase_short, fd.momentum_short, "
            "r.rating, r.wins, r.losses, "
            "sa.name "
            "FROM fighters f "
            "LEFT JOIN weight_classes wc "
            "  ON wc.weight_class_id = f.weight_class_id "
            "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
            "LEFT JOIN fighter_descriptors fd "
            "  ON fd.fighter_id = f.fighter_id "
            "LEFT JOIN rankings r "
            "  ON r.fighter_id = f.fighter_id "
            "  AND r.weight_class_id = f.weight_class_id "
            "  AND r.promotion_id = f.current_promotion_id "
            "LEFT JOIN style_archetypes sa "
            "  ON sa.style_archetype_id = f.fight_style_archetype_id "
            "WHERE f.fighter_id=?",
            (fid,),
        ).fetchone()
        if not row:
            return None
        (fid2, fn, ln, nick, wc_id, gender, mkt,
         height_cm, reach_cm, stance, portrait_path,
         dob, _style_arch_id,
         wc_name, w, l, d, ws, ls,
         stage_short, mom_short, rating, r_wins, r_losses,
         style_archetype_name) = row
        w = w or 0; l = l or 0; d = d or 0
        record_str = f"{w}-{l}" + (f"-{d}" if d else "")
        # Compute rank within the WC (1-15 or "Unranked").
        rank_str = "Unranked"
        rank_num = 0
        if wc_id:
            rank_row = conn.execute(
                "SELECT COUNT(*) + 1 FROM rankings r2 "
                "WHERE r2.weight_class_id=? AND r2.promotion_id="
                "  (SELECT current_promotion_id FROM fighters "
                "   WHERE fighter_id=?) "
                "  AND r2.rating > ?",
                (wc_id, fid, rating or 1000.0),
            ).fetchone()
            if rank_row:
                rank_int = int(rank_row[0])
                rank_num = rank_int if rank_int <= 15 else 0
                if rank_int <= 15:
                    rank_str = f"#{rank_int}"
        # Streak phrase (SHORT — voice-compliant).
        streak_phrase = ""
        if ws and ws >= 3:
            streak_phrase = f"{ws}-fight win streak"
        elif ls and ls >= 3:
            streak_phrase = f"{ls}-fight skid"
        elif ws and ws >= 1:
            streak_phrase = f"won {ws} straight"
        elif ls and ls >= 1:
            streak_phrase = f"dropped {ls} in a row"
        # MM1.2 — compute age from DOB + sim clock.
        age = None
        if dob:
            clock_row = conn.execute(
                "SELECT simulation_clock.current_date "
                "FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            ref_str = clock_row[0] if clock_row else None
            if ref_str:
                try:
                    dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                    ref_dt = datetime.strptime(ref_str, "%Y-%m-%d")
                    age = ref_dt.year - dob_dt.year
                    if (ref_dt.month, ref_dt.day) < (dob_dt.month, dob_dt.day):
                        age -= 1
                except (ValueError, TypeError):
                    pass
        # MM1.2 — compute the 9 corner-slot fields.
        popularity_tier = _popularity_tier(mkt)
        momentum_label = _momentum_label(ws, ls)
        recent_form = _recent_form(conn, fid2, 5)
        title_chip = _title_chip(conn, fid2)
        # Champion tier (gold for champion, silver for top-5, steel else).
        champion_tier = "champion" if title_chip["holds_title"] else (
            "top5" if 1 <= rank_num <= 5 else "steel")
        return {
            "fighter_id": fid2,
            "name": f"{fn} {ln}".strip(),
            "nickname": nick or "",
            "display_name": f'{fn} "{nick}" {ln}' if nick else f"{fn} {ln}",
            "weight_class_id": wc_id,
            "weight_class_name": wc_name or "—",
            "weight_class_short": _short_wc(wc_name),
            "gender": gender,
            "record_str": record_str,
            "wins": w, "losses": l, "draws": d,
            "win_streak": ws or 0, "loss_streak": ls or 0,
            "stage_short": _decode_label(stage_short) if stage_short else "",
            "momentum_short": _decode_label(mom_short) if mom_short else "",
            "streak_phrase": streak_phrase,
            "rank_str": rank_str,
            "rank_num": rank_num,
            "has_portrait": bool(portrait_path),
            "height_cm": height_cm,
            "reach_cm": reach_cm,
            "stance": stance or "",
            # Phase 7 / Task A2 — `marketability` raw int DROPPED
            # from the brief (per §17.4 "Rich Not Thin"). The voice
            # phrase `popularity_tier` below carries the same info
            # in voice form. Server-side matchup scoring reads
            # marketability via `_build_fighter_dict_for_matchup`.
            # MM1.2 — 9 corner-slot fields:
            "popularity_tier": popularity_tier,
            "momentum_label": momentum_label,
            "recent_form": recent_form,
            "title_chip": title_chip,
            "champion_tier": champion_tier,
            "age": age,
            "style_archetype_name": style_archetype_name or "Balanced",
            "date_of_birth": dob,
        }

    def _get_booked_fights_for_event(self, conn, event_id):
        """Fetch all booked fights for an event, with matchup_phrase +
        might-framed analysis for each fight's chip + voice phrases.

        Returns fights sorted by card_position (main event first).

        MM1.3 (Matchmaking V2): the analysis returned per fight is
        "might"-framed — NO predicted_winner, NO predicted_method, NO
        confidence_word, NO upset_risk, NO raw matchup_score in the
        response. The chip shows only the matchup_phrase (voice tier)
        + the style_matchup_phrase / early_read_phrase /
        excitement_phrase voice lines. Definitive punditry internals
        are still computed (for AI matchmaking / news generation) but
        never surfaced to the UI.

        HW3.5 (docs/Hardening_Phase.md §HW3.5): each fight now also
        carries a `memories` field — a list of (memory_type, phrase)
        tuples from memory_engine.surface_memories. These are the
        "rematch? former teammates? shared gym?" voice phrases that
        give a booked fight context. surface_memories is READ-ONLY
        (memory_engine D3) + never raises (D6) — safe to call here.
        """
        fight_rows = conn.execute(
            "SELECT f.fight_id, f.card_slot, f.is_title_fight, "
            "f.scheduled_rounds, f.weight_class_id, "
            "ec.card_position, "
            "wc.name, "
            "fpa.fighter_id AS red_id, "
            "fpb.fighter_id AS blue_id "
            "FROM fights f "
            "JOIN event_cards ec ON ec.fight_id=f.fight_id "
            "LEFT JOIN weight_classes wc "
            "  ON wc.weight_class_id=f.weight_class_id "
            "JOIN fight_participants fpa "
            "  ON fpa.fight_id=f.fight_id AND fpa.corner='red' "
            "JOIN fight_participants fpb "
            "  ON fpb.fight_id=f.fight_id AND fpb.corner='blue' "
            "WHERE f.event_id=? "
            "ORDER BY ec.card_position ASC",
            (event_id,),
        ).fetchall()
        booked = []
        for (fight_id, card_slot, is_title, rounds, wc_id,
             card_position, wc_name,
             red_id, blue_id) in fight_rows:
            red_info = self._fighter_brief(conn, red_id) or {}
            blue_info = self._fighter_brief(conn, blue_id) or {}
            # Compute matchup_score (kept internal — never shown raw).
            red_dict = _build_fighter_dict_for_matchup(conn, red_id) or {}
            blue_dict = _build_fighter_dict_for_matchup(conn, blue_id) or {}
            matchup_score = _compute_matchup_score(
                conn, red_dict, blue_dict,
            )
            matchup_phrase, matchup_color = _matchup_quality_phrase(
                matchup_score,
            )
            # MM1.3 — compute might-framed analysis (no predictions).
            analysis = self._compute_might_analysis(
                conn, red_id, blue_id, seed=fight_id,
            )
            # MM1.2 — rivalry chip on the card.
            rivalry = _rivalry_heat(conn, red_id, blue_id)
            # HW3.5 — surface memories (rematch / shared gym / former
            # teammates / injuries / title-fight history / etc.) for
            # this fighter pair. READ-ONLY + never raises — a failed
            # lookup returns an empty list, not an error.
            memories = _surface_memories_safe(conn, red_id, blue_id)
            booked.append({
                "fight_id": fight_id,
                "card_slot": card_slot,
                "card_position": card_position,
                "is_title_fight": bool(is_title),
                "scheduled_rounds": rounds,
                "weight_class_id": wc_id,
                "weight_class_name": wc_name or "—",
                "red_fighter": red_info,
                "blue_fighter": blue_info,
                # MM1.3 — matchup_score is INTERNAL ONLY (kept for AI /
                # news gen). The UI must NEVER render it.
                "matchup_score": round(matchup_score, 1),
                "matchup_phrase": matchup_phrase,
                "matchup_color": matchup_color,
                "analysis": analysis,
                "rivalry": rivalry,
                # HW3.5 — list of (memory_type, phrase) tuples.
                "memories": memories,
            })
        return booked

    def _compute_might_analysis(self, conn, red_id, blue_id, seed=None):
        """Compute the "might"-framed analysis for a fighter pair.

        Per MM1.3: returns ONLY voice phrases — no predicted_winner,
        no predicted_method, no confidence_word, no upset_risk, no
        raw matchup_score. The four keys the UI renders are:
          - style_matchup_phrase (style clash take)
          - early_read_phrase (on-paper read)
          - excitement_phrase (might-framed excitement)
          - matchup_phrase (voice tier only — caller-supplied)

        The punditry engine still computes the definitive internals
        (predicted_winner / confidence / etc.) for AI + news gen, but
        they are NOT returned here.
        """
        import random as _random
        rng = _random.Random(seed or (red_id + blue_id))
        try:
            from punditry import (
                _compute_predicted_winner, _fighter_style_archetype_name,
                _compute_excitement, _compute_style_edge,
            )
            fav_id, und_id, gap = _compute_predicted_winner(
                conn, red_id, blue_id, rng=rng,
            )
            style_a = _fighter_style_archetype_name(conn, red_id)
            style_b = _fighter_style_archetype_name(conn, blue_id)
            excite = _compute_excitement(conn, red_id, blue_id)
            style_edge = _compute_style_edge(
                conn, fav_id, und_id, rng=rng,
            )
        except Exception as e:
            print(f"[_compute_might_analysis] {e}", flush=True)
            style_a = "Balanced"
            style_b = "Balanced"
            gap = 0.0
            excite = 50
            style_edge = ""
        return {
            # MM1.3 — only might-framed phrases. NO predicted_winner,
            # NO predicted_method, NO confidence_word, NO upset_risk,
            # NO raw matchup_score.
            "style_matchup_phrase": _style_matchup_phrase(
                style_a, style_b, rng=rng,
            ),
            "early_read_phrase": _early_read_phrase(gap, rng=rng),
            "excitement_phrase": _excitement_phrase_might(
                excite, rng=rng,
            ),
            "style_edge": style_edge,  # legacy voice phrase, kept
        }

    def book_fight(self, event_id, red_fighter_id, blue_fighter_id,
                    card_slot=None):
        """Book a fight on the card.

        Inserts a fights row + 2 fight_participants rows + 1 event_cards
        row. Computes the matchup_score + punditry analysis and returns
        them so the JS can update the chip + voice phrases without a
        separate fetch.

        Per docs/MASTER_PLAN_MATCHMAKING.md §"Backend changes":
          - card_slot: 'main_event' / 'co_main' / 'featured_prelim' /
            'prelim' / 'opener'. If None, auto-assigns based on current
            card size (first fight = main_event, 2nd = co_main, etc.).

        Returns:
          {ok, fight_id, card_slot, matchup_score, matchup_phrase,
           matchup_color, analysis}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            eid = int(event_id or 0)
            red_id = int(red_fighter_id or 0)
            blue_id = int(blue_fighter_id or 0)
            if not eid or not red_id or not blue_id:
                return {"ok": False, "error": "Missing event or fighter IDs."}
            if red_id == blue_id:
                return {"ok": False,
                        "error": "A fighter can't fight themselves."}

            # Verify the event belongs to the player's promo + is
            # still scheduled (can't book on completed events).
            ev_row = conn.execute(
                "SELECT promotion_id, status, event_date FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row:
                return {"ok": False, "error": "Event not found."}
            if ev_row[0] != pid:
                return {"ok": False,
                        "error": "This event belongs to another promotion."}
            if ev_row[1] != 'scheduled':
                return {"ok": False,
                        "error": f"Event status is '{ev_row[1]}' — can only book on 'scheduled' events."}
            event_date_str = ev_row[2]

            # Verify both fighters are on the player's roster + same
            # gender (defensive — mixed-gender fights are forbidden).
            f_row = conn.execute(
                "SELECT fighter_id, weight_class_id, gender, "
                "current_promotion_id, is_active, is_retired "
                "FROM fighters WHERE fighter_id IN (?, ?)",
                (red_id, blue_id),
            ).fetchall()
            if len(f_row) != 2:
                return {"ok": False, "error": "Fighter not found."}
            r = f_row[0]; b = f_row[1]
            # Order may not match — find which is which.
            if r[0] != red_id:
                r, b = b, r
            r_fid, r_wc, r_gender, r_promo, r_active, r_retired = r
            b_fid, b_wc, b_gender, b_promo, b_active, b_retired = b
            if r_promo != pid or b_promo != pid:
                return {"ok": False,
                        "error": "Both fighters must be on your roster."}
            if not r_active or not b_active or r_retired or b_retired:
                return {"ok": False,
                        "error": "Both fighters must be active."}
            if r_gender != b_gender:
                return {"ok": False,
                        "error": "Mixed-gender fights aren't allowed."}
            if r_wc != b_wc:
                return {"ok": False,
                        "error": "Fighters must be in the same weight class."}

            # MM3.4 — Re-validate at book_fight time. The roster may
            # have been loaded minutes ago, but the fighter's state may
            # have changed since (injury sustained on a tick, suspended
            # by an event, retired by the annual lifecycle tick, or
            # booked on another event by the rival AI). Each check
            # returns a specific error so the JS can show the right
            # message to the player. Per docs/MASTER_PLAN_MATCHMAKING_V2.md
            # §3.4.
            # 1. Active injuries.
            for fid, label in ((red_id, "Red"), (blue_id, "Blue")):
                inj = conn.execute(
                    "SELECT 1 FROM injuries WHERE fighter_id=? "
                    "AND is_active=1 LIMIT 1",
                    (fid,),
                ).fetchone()
                if inj:
                    fname = _fighter_display_name(conn, fid)
                    return {"ok": False,
                            "error": f"{fname} is injured and unavailable to fight."}
            # 2. Active suspensions.
            for fid, label in ((red_id, "Red"), (blue_id, "Blue")):
                sus = conn.execute(
                    "SELECT 1 FROM suspensions WHERE fighter_id=? "
                    "AND is_active=1 LIMIT 1",
                    (fid,),
                ).fetchone()
                if sus:
                    fname = _fighter_display_name(conn, fid)
                    return {"ok": False,
                            "error": f"{fname} is suspended and unavailable to fight."}
            # 3. Retired (defensive — already checked above, but a
            # concurrent tick may have flipped the flag between the
            # SELECT and now).
            for fid in (red_id, blue_id):
                ret = conn.execute(
                    "SELECT is_retired FROM fighters WHERE fighter_id=?",
                    (fid,),
                ).fetchone()
                if ret and ret[0]:
                    fname = _fighter_display_name(conn, fid)
                    return {"ok": False,
                            "error": f"{fname} has retired and can't be booked."}
            # 4. Cross-event ±7-day booking check. A fighter already
            # booked on another scheduled event within ±7 days of
            # THIS event's date is unavailable (per MM3.1).
            if event_date_str:
                for fid in (red_id, blue_id):
                    xrow = conn.execute(
                        "SELECT e.event_name, e.event_date "
                        "FROM fight_participants fp "
                        "JOIN fights f ON f.fight_id = fp.fight_id "
                        "JOIN events e ON e.event_id = f.event_id "
                        "WHERE fp.fighter_id = ? "
                        "  AND e.status = 'scheduled' "
                        "  AND e.event_id != ? "
                        "  AND ABS(julianday(e.event_date) - julianday(?)) <= 7 "
                        "LIMIT 1",
                        (fid, eid, event_date_str),
                    ).fetchone()
                    if xrow:
                        fname = _fighter_display_name(conn, fid)
                        other_event, other_date = xrow
                        return {"ok": False,
                                "error": (f"{fname} is already booked on "
                                          f"'{other_event}' ({other_date}) — "
                                          f"can't double-book within a week.")}

            # MM3.3 — Last-minute rejection. If the event is ≤ 14 days
            # away, run the personality-based willingness check on
            # BOTH fighters. If either rejects, write a news item +
            # return rejected_by. Per docs/MASTER_PLAN_MATCHMAKING_V2.md
            # §3.3.
            is_short_notice = False
            if event_date_str:
                try:
                    ev_dt = datetime.strptime(event_date_str, "%Y-%m-%d")
                    today_str = get_clock(conn)[0] if get_clock(conn) else None
                    if today_str:
                        today_dt = datetime.strptime(today_str, "%Y-%m-%d")
                        is_short_notice = (ev_dt - today_dt).days <= 14
                except (ValueError, TypeError):
                    is_short_notice = False
            if is_short_notice:
                event_name_row = conn.execute(
                    "SELECT event_name FROM events WHERE event_id=?",
                    (eid,),
                ).fetchone()
                event_name = event_name_row[0] if event_name_row else f"Event {eid}"
                # Check red first, then blue — first rejection wins.
                for fid, opp_id in ((red_id, blue_id), (blue_id, red_id)):
                    willingness = _short_notice_willingness(conn, fid)
                    if willingness < 30:
                        fname = _fighter_display_name(conn, fid)
                        opp_name = _fighter_display_name(conn, opp_id)
                        # Write the rejection news item (topic='release'
                        # is wrong; use 'signing' for booking-related
                        # news per the established pattern).
                        src_row = conn.execute(
                            "SELECT news_source_id FROM news_sources "
                            "WHERE name = 'System Feed'"
                        ).fetchone()
                        if src_row:
                            # NEWS-SPAM-MEMORY-CHECK — short-notice
                            # bout declines are BACKGROUND-tier (low-
                            # stakes booking churn). Was defaulting to
                            # ROUTINE via direct INSERT.
                            conn.execute(
                                "INSERT INTO news_items (news_source_id, "
                                "headline, body, sentiment, topic, fighter_id, "
                                "promotion_id, published_at, importance) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (src_row[0],
                                 f"{fname} turns down short-notice bout",
                                 (f"{fname} has turned down a short-notice "
                                  f"bout against {opp_name} at {event_name}, "
                                  f"citing the need for a proper training camp."),
                                 "neutral",
                                 "booking",
                                 fid,
                                 pid,
                                 get_clock(conn)[0] if get_clock(conn) else None,
                                 "BACKGROUND"),
                            )
                        conn.commit()
                        return {
                            "ok": False,
                            "rejected_by": fid,
                            "rejected_by_name": fname,
                            "opponent_id": opp_id,
                            "opponent_name": opp_name,
                            "event_name": event_name,
                            "reason": "short_notice",
                            "error": (f"{fname} has turned down a short-notice "
                                      f"bout against {opp_name} at {event_name}, "
                                      f"citing the need for a proper training camp."),
                        }

            # Verify neither fighter is already booked on this card.
            already_booked = conn.execute(
                "SELECT fp.fighter_id "
                "FROM fights f "
                "JOIN fight_participants fp ON fp.fight_id=f.fight_id "
                "WHERE f.event_id=? AND fp.fighter_id IN (?, ?)",
                (eid, red_id, blue_id),
            ).fetchall()
            if already_booked:
                return {"ok": False,
                        "error": "One of these fighters is already booked on this card."}

            # Determine card_slot if not provided.
            if not card_slot:
                # Count current fights on the card.
                cnt_row = conn.execute(
                    "SELECT COUNT(*) FROM fights WHERE event_id=?",
                    (eid,),
                ).fetchone()
                n = int(cnt_row[0] or 0)
                if n == 0:
                    card_slot = 'main_event'
                elif n == 1:
                    card_slot = 'co_main'
                elif n <= 3:
                    card_slot = 'featured_prelim'
                else:
                    card_slot = 'prelim'

            # Validate card_slot.
            valid_slots = ('main_event', 'co_main', 'featured_prelim',
                           'prelim', 'opener')
            if card_slot not in valid_slots:
                return {"ok": False,
                        "error": f"Invalid card_slot: {card_slot}"}

            # Insert the fights row.
            scheduled_rounds = 5 if (card_slot == 'main_event') else 3
            new_fight_id = conn.execute(
                "INSERT INTO fights (event_id, weight_class_id, "
                "bout_type, card_slot, is_title_fight, round_limit, "
                "scheduled_rounds) "
                "VALUES (?, ?, ?, ?, 0, 3, ?)",
                (eid, r_wc, card_slot, card_slot, scheduled_rounds),
            ).lastrowid

            # Insert the 2 fight_participants rows.
            conn.execute(
                "INSERT INTO fight_participants (fight_id, fighter_id, "
                "corner) VALUES (?, ?, 'red')",
                (new_fight_id, red_id),
            )
            conn.execute(
                "INSERT INTO fight_participants (fight_id, fighter_id, "
                "corner) VALUES (?, ?, 'blue')",
                (new_fight_id, blue_id),
            )

            # Insert the event_cards row (card_position = current count + 1).
            pos_row = conn.execute(
                "SELECT COALESCE(MAX(card_position), 0) + 1 "
                "FROM event_cards WHERE event_id=?",
                (eid,),
            ).fetchone()
            card_position = int(pos_row[0]) if pos_row else 1
            conn.execute(
                "INSERT INTO event_cards (event_id, fight_id, "
                "card_position, card_tier, is_main_event, is_co_main) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, new_fight_id, card_position, card_slot,
                 1 if card_slot == 'main_event' else 0,
                 1 if card_slot == 'co_main' else 0),
            )

            conn.commit()

            # Compute the matchup_score + analysis to return.
            red_dict = _build_fighter_dict_for_matchup(conn, red_id) or {}
            blue_dict = _build_fighter_dict_for_matchup(conn, blue_id) or {}
            matchup_score = _compute_matchup_score(conn, red_dict, blue_dict)
            matchup_phrase, matchup_color = _matchup_quality_phrase(
                matchup_score,
            )

            # MM1.3 — compute + persist the punditry analysis for this
            # fight (so the chip + voice phrases are stable across
            # reloads). The persisted row keeps the definitive
            # predicted_winner/method/confidence (used by AI + news
            # generation), but the response returned to JS uses the
            # might-framed analysis (no predictions, no raw score).
            try:
                from punditry import generate_matchup_analysis
                generate_matchup_analysis(
                    conn, red_id, blue_id, fight_id=new_fight_id,
                    event_id=eid,
                )
                conn.commit()
            except Exception as e:
                print(f"[api.book_fight] analysis: {e}", flush=True)

            # HW9.2 — wire memory resurfacing into the player's fight
            # booking path. After the fight is INSERTed + the punditry
            # analysis is generated, call surface_memories to find any
            # relevant history between the two fighters. If memories
            # are found, write a memory_resurfacing news item ("fight
            # preview" beat). This is the same wiring the rival AI's
            # schedule_next_event got — the player's manually-booked
            # fights get the same narrative treatment.
            try:
                from news import generate_fight_preview_memory_news
                generate_fight_preview_memory_news(
                    conn, fight_id=new_fight_id,
                    fighter_a_id=red_id,
                    fighter_b_id=blue_id,
                    event_id=eid,
                    promotion_id=pid,
                )
                conn.commit()
            except Exception as e:
                print(f"[api.book_fight] memory_resurfacing: {e}",
                      flush=True)

            # MM1.3 — return the might-framed analysis (no predictions).
            analysis = self._compute_might_analysis(
                conn, red_id, blue_id, seed=new_fight_id,
            )
            rivalry = _rivalry_heat(conn, red_id, blue_id)
            # HW3.5 — surface memories for this fighter pair so the
            # JS can render "Last met three years ago" / "Former
            # training partners" / etc. chips next to the booking.
            memories = _surface_memories_safe(conn, red_id, blue_id)

            # HW3.4 — log a 'book' decision so the echoes engine can
            # surface "Your decision to main-event X vs Y at [Event]
            # was your Nth-biggest card of the year" after the event
            # completes. Per docs/Hardening_Phase.md §HW3.4 (echoes
            # quality audit found that booking_echo never fired
            # because no 'book' decisions were being logged).
            try:
                from player_decisions import log_decision, TYPE_BOOK
                log_decision(
                    conn, TYPE_BOOK,
                    target_event_id=eid,
                    target_promo_id=pid,
                    context={"red_fighter_id": red_id,
                             "blue_fighter_id": blue_id,
                             "card_slot": card_slot,
                             "fight_id": new_fight_id,
                             "backfilled": False},
                )
            except Exception as e:
                print(f"[api.book_fight] WARN: log_decision "
                      f"failed: {e}", flush=True)

            return {
                "ok": True,
                "fight_id": new_fight_id,
                "card_slot": card_slot,
                "card_position": card_position,
                # MM1.3 — matchup_score is INTERNAL ONLY (kept for AI /
                # news gen). The UI must NEVER render it.
                "matchup_score": round(matchup_score, 1),
                "matchup_phrase": matchup_phrase,
                "matchup_color": matchup_color,
                "analysis": analysis,
                "rivalry": rivalry,
                # HW3.5 — list of {"type", "phrase"} dicts for the
                # matchmaking screen's "History" panel.
                "memories": memories,
            }
        except Exception as e:
            print(f"[api.book_fight] {e}\n{traceback.format_exc()}",
                  flush=True)
            conn.rollback()
            return {"ok": False, "error": str(e)}

    def remove_fight(self, fight_id):
        """Remove a fight from the card.

        Deletes the fights row (cascade removes fight_participants +
        event_cards). Reorders remaining fights so card_position stays
        sequential (1, 2, 3, ...).

        Returns:
          {ok, removed_fight_id, remaining_count}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            fid = int(fight_id or 0)
            if not fid:
                return {"ok": False, "error": "Missing fight_id."}

            # Verify the fight belongs to the player's promo.
            f_row = conn.execute(
                "SELECT e.promotion_id, e.event_id "
                "FROM fights f JOIN events e ON e.event_id=f.event_id "
                "WHERE f.fight_id=?",
                (fid,),
            ).fetchone()
            if not f_row:
                return {"ok": False, "error": "Fight not found."}
            if f_row[0] != pid:
                return {"ok": False,
                        "error": "This fight belongs to another promotion."}
            event_id = f_row[1]

            # Verify the event is still scheduled.
            status_row = conn.execute(
                "SELECT status FROM events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if status_row and status_row[0] != 'scheduled':
                return {"ok": False,
                        "error": f"Event status is '{status_row[0]}' — can only remove from 'scheduled' events."}

            # Delete the fight (cascade handles fight_participants +
            # event_cards).
            conn.execute("DELETE FROM fights WHERE fight_id=?", (fid,))
            conn.commit()

            # Reorder remaining fights so card_position is sequential.
            self._reorder_card_positions(conn, event_id)

            # Count remaining fights.
            cnt_row = conn.execute(
                "SELECT COUNT(*) FROM fights WHERE event_id=?",
                (event_id,),
            ).fetchone()
            remaining = int(cnt_row[0] or 0) if cnt_row else 0

            return {
                "ok": True,
                "removed_fight_id": fid,
                "event_id": event_id,
                "remaining_count": remaining,
            }
        except Exception as e:
            print(f"[api.remove_fight] {e}\n{traceback.format_exc()}",
                  flush=True)
            conn.rollback()
            return {"ok": False, "error": str(e)}

    def reorder_fights(self, event_id, fight_order):
        """Update card_slot + card_position for all fights on the card.

        Per docs/MASTER_PLAN_MATCHMAKING.md §"Backend changes":
          - first fight = main_event
          - second fight = co_main
          - rest = featured_prelim / prelim (based on position)

        Args:
          event_id: int
          fight_order: list of fight_ids in the new order (1st = main
            event, 2nd = co_main, etc.)

        Returns:
          {ok, event_id, reordered_count}
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            eid = int(event_id or 0)
            if not eid:
                return {"ok": False, "error": "Missing event_id."}
            if not isinstance(fight_order, (list, tuple)):
                return {"ok": False, "error": "fight_order must be a list."}

            # Verify the event belongs to the player's promo.
            ev_row = conn.execute(
                "SELECT promotion_id, status FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row:
                return {"ok": False, "error": "Event not found."}
            if ev_row[0] != pid:
                return {"ok": False,
                        "error": "This event belongs to another promotion."}
            if ev_row[1] != 'scheduled':
                return {"ok": False,
                        "error": f"Event status is '{ev_row[1]}' — can only reorder 'scheduled' events."}

            # Update each fight's card_slot + card_position.
            for idx, fid in enumerate(fight_order):
                fid = int(fid)
                if idx == 0:
                    slot = 'main_event'
                elif idx == 1:
                    slot = 'co_main'
                elif idx <= 3:
                    slot = 'featured_prelim'
                else:
                    slot = 'prelim'
                # Update the fight's card_slot.
                conn.execute(
                    "UPDATE fights SET card_slot=?, "
                    "scheduled_rounds=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE fight_id=? AND event_id=?",
                    (slot, 5 if slot == 'main_event' else 3, fid, eid),
                )
                # Update the event_cards row.
                conn.execute(
                    "UPDATE event_cards SET card_position=?, card_tier=?, "
                    "is_main_event=?, is_co_main=?, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE fight_id=? AND event_id=?",
                    (idx + 1, slot,
                     1 if slot == 'main_event' else 0,
                     1 if slot == 'co_main' else 0,
                     fid, eid),
                )
            conn.commit()
            return {
                "ok": True,
                "event_id": eid,
                "reordered_count": len(fight_order),
            }
        except Exception as e:
            print(f"[api.reorder_fights] {e}\n{traceback.format_exc()}",
                  flush=True)
            conn.rollback()
            return {"ok": False, "error": str(e)}

    def _reorder_card_positions(self, conn, event_id):
        """Re-number card_position sequentially for all fights on the
        card. Called after a fight is removed so positions stay
        1, 2, 3, ... (no gaps).
        """
        rows = conn.execute(
            "SELECT f.fight_id, f.card_slot "
            "FROM fights f "
            "JOIN event_cards ec ON ec.fight_id=f.fight_id "
            "WHERE f.event_id=? "
            "ORDER BY ec.card_position ASC",
            (event_id,),
        ).fetchall()
        for idx, (fid, old_slot) in enumerate(rows):
            if idx == 0:
                slot = 'main_event'
            elif idx == 1:
                slot = 'co_main'
            elif idx <= 3:
                slot = 'featured_prelim'
            else:
                slot = 'prelim'
            if slot != old_slot:
                conn.execute(
                    "UPDATE fights SET card_slot=?, "
                    "scheduled_rounds=?, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE fight_id=?",
                    (slot, 5 if slot == 'main_event' else 3, fid),
                )
            conn.execute(
                "UPDATE event_cards SET card_position=?, card_tier=?, "
                "is_main_event=?, is_co_main=?, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE fight_id=? AND event_id=?",
                (idx + 1, slot,
                 1 if slot == 'main_event' else 0,
                 1 if slot == 'co_main' else 0,
                 fid, event_id),
            )
        conn.commit()

    def get_fight_analysis(self, red_fighter_id, blue_fighter_id):
        """Pre-fight analysis for a fighter pair (without booking).

        Per docs/MASTER_PLAN_MATCHMAKING_V2.md §MM1.3 + §MM1.6:
          - Returns ONLY "might"-framed voice phrases.
          - NO predicted_winner (definitive).
          - NO predicted_method (definitive).
          - NO confidence_word / confidence_pct.
          - NO upset_risk.
          - NO raw matchup_score (the chip shows the voice phrase
            tier only, no number).
          - Returns: style_matchup_phrase, early_read_phrase,
            excitement_phrase, matchup_phrase (voice tier).

        Used by the Compare modal to show the analysis BEFORE the
        player commits to booking the fight.

        Does NOT write to the DB (the analysis is regenerated when
        the fight is actually booked via book_fight).
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            red_id = int(red_fighter_id or 0)
            blue_id = int(blue_fighter_id or 0)
            if not red_id or not blue_id:
                return {"ok": False, "error": "Missing fighter IDs."}
            if red_id == blue_id:
                return {"ok": False,
                        "error": "A fighter can't fight themselves."}

            # Compute matchup_score (kept internal — never shown raw).
            red_dict = _build_fighter_dict_for_matchup(conn, red_id) or {}
            blue_dict = _build_fighter_dict_for_matchup(conn, blue_id) or {}
            matchup_score = _compute_matchup_score(conn, red_dict, blue_dict)
            matchup_phrase, matchup_color = _matchup_quality_phrase(
                matchup_score,
            )

            # MM1.3 — might-framed analysis (no predictions).
            analysis = self._compute_might_analysis(
                conn, red_id, blue_id, seed=(red_id + blue_id),
            )

            # Get fighter briefs (name, record, etc.) for the modal.
            red_brief = self._fighter_brief(conn, red_id) or {}
            blue_brief = self._fighter_brief(conn, blue_id) or {}

            # MM1.2 — rivalry heat between the two fighters.
            rivalry = _rivalry_heat(conn, red_id, blue_id)

            return {
                "ok": True,
                "red_fighter": red_brief,
                "blue_fighter": blue_brief,
                # MM1.3 — matchup_score is INTERNAL ONLY.
                "matchup_score": round(matchup_score, 1),
                "matchup_phrase": matchup_phrase,
                "matchup_color": matchup_color,
                "analysis": analysis,
                "rivalry": rivalry,
            }
        except Exception as e:
            print(f"[api.get_fight_analysis] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_fight_tale_of_tape(self, fight_id):
        """Return tale-of-tape data for a booked fight.

        Used by the Tale of Tape modal. Returns both fighters' full
        info (height, reach, age, record, style, last 5 fights as
        W/L colored blocks) + weight class + bout type + title status.
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            fid = int(fight_id or 0)
            if not fid:
                return {"ok": False, "error": "Missing fight_id."}

            f_row = conn.execute(
                "SELECT f.fight_id, f.event_id, f.card_slot, "
                "f.is_title_fight, f.scheduled_rounds, "
                "f.weight_class_id, wc.name, wc.gender, "
                "fpa.fighter_id AS red_id, "
                "fpb.fighter_id AS blue_id "
                "FROM fights f "
                "LEFT JOIN weight_classes wc "
                "  ON wc.weight_class_id=f.weight_class_id "
                "JOIN fight_participants fpa "
                "  ON fpa.fight_id=f.fight_id AND fpa.corner='red' "
                "JOIN fight_participants fpb "
                "  ON fpb.fight_id=f.fight_id AND fpb.corner='blue' "
                "WHERE f.fight_id=?",
                (fid,),
            ).fetchone()
            if not f_row:
                return {"ok": False, "error": "Fight not found."}
            (fid2, eid, slot, is_title, rounds, wc_id, wc_name, wc_gender,
             red_id, blue_id) = f_row

            # Verify event belongs to player's promo.
            ev_row = conn.execute(
                "SELECT promotion_id FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row or ev_row[0] != pid:
                return {"ok": False,
                        "error": "This fight belongs to another promotion."}

            red_tape = self._fighter_tale_of_tape(conn, red_id)
            blue_tape = self._fighter_tale_of_tape(conn, blue_id)

            return {
                "ok": True,
                "fight_id": fid2,
                "event_id": eid,
                "card_slot": slot,
                "is_title_fight": bool(is_title),
                "scheduled_rounds": rounds,
                "weight_class_name": wc_name or "—",
                "weight_class_gender": wc_gender or "male",
                "red_fighter": red_tape,
                "blue_fighter": blue_tape,
            }
        except Exception as e:
            print(f"[api.get_fight_tale_of_tape] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def _fighter_tale_of_tape(self, conn, fighter_id):
        """Build the tale-of-tape dict for one fighter."""
        if not fighter_id:
            return None
        brief = self._fighter_brief(conn, fighter_id) or {}
        # Fetch DOB, height, reach, stance + style archetype name.
        row = conn.execute(
            "SELECT f.date_of_birth, f.height_cm, f.reach_cm, "
            "f.stance, f.handedness, "
            "sa.name, sa.description "
            "FROM fighters f "
            "LEFT JOIN style_archetypes sa "
            "  ON sa.style_archetype_id=f.fight_style_archetype_id "
            "WHERE f.fighter_id=?",
            (fighter_id,),
        ).fetchone()
        if row:
            (dob, height_cm, reach_cm, stance, handedness,
             style_name, style_desc) = row
        else:
            dob = height_cm = reach_cm = stance = handedness = None
            style_name = style_desc = None
        # Compute age.
        age = None
        if dob:
            clock_row = conn.execute(
                "SELECT simulation_clock.current_date "
                "FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            ref_str = clock_row[0] if clock_row else None
            if ref_str:
                try:
                    dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                    ref_dt = datetime.strptime(ref_str, "%Y-%m-%d")
                    age = ref_dt.year - dob_dt.year
                    if (ref_dt.month, ref_dt.day) < (dob_dt.month, dob_dt.day):
                        age -= 1
                except (ValueError, TypeError):
                    pass
        # Last 5 fights as W/L/D blocks.
        last5_rows = conn.execute(
            "SELECT outcome, result_type, finish_round "
            "FROM fight_history "
            "WHERE fighter_id=? "
            "ORDER BY fight_history_id DESC LIMIT 5",
            (fighter_id,),
        ).fetchall()
        last5 = []
        for (outcome, rtype, rnd) in last5_rows:
            letter = 'W' if outcome == 'win' else (
                'L' if outcome == 'loss' else (
                    'D' if outcome == 'draw' else 'N'))
            last5.append({
                "letter": letter,
                "outcome": outcome,
                "result_type": rtype or "",
                "finish_round": rnd,
            })
        # Champion status.
        champ_row = conn.execute(
            "SELECT t.title_id, wc.name "
            "FROM titles t "
            "JOIN weight_classes wc "
            "  ON wc.weight_class_id=t.weight_class_id "
            "WHERE t.current_champion_fighter_id=? "
            "  AND t.is_vacant=0",
            (fighter_id,),
        ).fetchone()
        champion_of = champ_row[1] if champ_row else None
        return {
            **brief,
            "age": age,
            "height_cm": height_cm,
            "reach_cm": reach_cm,
            "stance": stance or "orthodox",
            "handedness": handedness or "right",
            "style_archetype": style_name or "Balanced",
            "style_description": style_desc or "",
            "last_5": last5,
            "champion_of": champion_of,
        }

    def get_fight_stakes(self, fight_id):
        """Return what's at stake for a booked fight.

        Used by the What's at Stake modal. Returns:
          - ranking implications: "If [Red] wins → projected rank #X;
            if [Red] loses → projected rank #Y"
          - title shot proximity: "Winner is in line for a title shot
            against [Champion Name]"
          - title fight status (if applicable)
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            fid = int(fight_id or 0)
            if not fid:
                return {"ok": False, "error": "Missing fight_id."}

            f_row = conn.execute(
                "SELECT f.event_id, f.card_slot, f.is_title_fight, "
                "f.weight_class_id, wc.name, "
                "fpa.fighter_id AS red_id, "
                "fpb.fighter_id AS blue_id "
                "FROM fights f "
                "LEFT JOIN weight_classes wc "
                "  ON wc.weight_class_id=f.weight_class_id "
                "JOIN fight_participants fpa "
                "  ON fpa.fight_id=f.fight_id AND fpa.corner='red' "
                "JOIN fight_participants fpb "
                "  ON fpb.fight_id=f.fight_id AND fpb.corner='blue' "
                "WHERE f.fight_id=?",
                (fid,),
            ).fetchone()
            if not f_row:
                return {"ok": False, "error": "Fight not found."}
            (eid, slot, is_title, wc_id, wc_name,
             red_id, blue_id) = f_row

            # Verify event belongs to player's promo.
            ev_row = conn.execute(
                "SELECT promotion_id FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row or ev_row[0] != pid:
                return {"ok": False,
                        "error": "This fight belongs to another promotion."}

            red_brief = self._fighter_brief(conn, red_id) or {}
            blue_brief = self._fighter_brief(conn, blue_id) or {}

            # Compute projected ranks (rough heuristic: a win moves
            # the fighter up by 1-3 spots depending on opponent's
            # rank; a loss drops them by 2-5 spots).
            def _projected_rank(fighter_id, opponent_id, wc_id, outcome):
                """Compute projected rank for a fighter after a win/loss."""
                if not wc_id:
                    return "Unranked"
                # Current rating.
                me_row = conn.execute(
                    "SELECT rating FROM rankings "
                    "WHERE fighter_id=? AND weight_class_id=? "
                    "  AND promotion_id=?",
                    (fighter_id, wc_id, pid),
                ).fetchone()
                opp_row = conn.execute(
                    "SELECT rating FROM rankings "
                    "WHERE fighter_id=? AND weight_class_id=? "
                    "  AND promotion_id=?",
                    (opponent_id, wc_id, pid),
                ).fetchone()
                me_rating = float(me_row[0] if me_row and me_row[0] else 1000.0)
                opp_rating = float(opp_row[0] if opp_row and opp_row[0] else 1000.0)
                # ELO-like delta.
                if outcome == 'win':
                    delta = max(8, int(32 * (1 - 1 / (1 + 10 ** (
                        (opp_rating - me_rating) / 400)))))
                    new_rating = me_rating + delta
                else:
                    delta = max(8, int(32 * (1 / (1 + 10 ** (
                        (opp_rating - me_rating) / 400)))))
                    new_rating = me_rating - delta
                # Compute projected rank by counting how many fighters
                # in the WC have a higher rating.
                rank_row = conn.execute(
                    "SELECT COUNT(*) + 1 FROM rankings "
                    "WHERE weight_class_id=? AND promotion_id=? "
                    "  AND rating > ?",
                    (wc_id, pid, new_rating),
                ).fetchone()
                rank_int = int(rank_row[0]) if rank_row else 99
                return f"#{rank_int}" if rank_int <= 15 else "Unranked"

            red_wins_rank = _projected_rank(red_id, blue_id, wc_id, 'win')
            red_loses_rank = _projected_rank(red_id, blue_id, wc_id, 'loss')
            blue_wins_rank = _projected_rank(blue_id, red_id, wc_id, 'win')
            blue_loses_rank = _projected_rank(blue_id, red_id, wc_id, 'loss')

            # Title shot proximity — is the champion of this WC
            # a different fighter (not one of these two)?
            title_row = conn.execute(
                "SELECT t.title_id, t.current_champion_fighter_id, "
                "t.is_vacant, "
                "fi.first_name, fi.last_name "
                "FROM titles t "
                "LEFT JOIN fighters fi "
                "  ON fi.fighter_id=t.current_champion_fighter_id "
                "WHERE t.promotion_id=? AND t.weight_class_id=?",
                (pid, wc_id),
            ).fetchone() if wc_id else None
            champion_name = None
            is_vacant = False
            if title_row:
                _tid, champ_id, vacant, cfn, cln = title_row
                is_vacant = bool(vacant)
                if champ_id and champ_id not in (red_id, blue_id):
                    champion_name = f"{cfn} {cln}".strip() if cfn else None

            # Build voice phrases.
            red_implication = (
                f"If {red_brief.get('name', 'Red')} wins → projected "
                f"rank {red_wins_rank}; if {(red_brief.get('name', 'Red'))} "
                f"loses → projected rank {red_loses_rank}."
            )
            blue_implication = (
                f"If {blue_brief.get('name', 'Blue')} wins → projected "
                f"rank {blue_wins_rank}; if {(blue_brief.get('name', 'Blue'))} "
                f"loses → projected rank {blue_loses_rank}."
            )
            title_shot_phrase = None
            if champion_name:
                title_shot_phrase = (
                    f"The winner is in line for a title shot against "
                    f"{champion_name}."
                )
            elif is_vacant:
                title_shot_phrase = (
                    "The {wc} title is vacant — the winner could stake a claim."
                ).format(wc=wc_name or "division")
            title_fight_phrase = None
            if is_title:
                title_fight_phrase = (
                    f"This is a {wc_name or 'divisional'} title fight — "
                    "the belt is on the line."
                )

            return {
                "ok": True,
                "fight_id": fid,
                "event_id": eid,
                "weight_class_name": wc_name or "—",
                "is_title_fight": bool(is_title),
                "card_slot": slot,
                "red_fighter": red_brief,
                "blue_fighter": blue_brief,
                "red_projected_rank_win": red_wins_rank,
                "red_projected_rank_loss": red_loses_rank,
                "blue_projected_rank_win": blue_wins_rank,
                "blue_projected_rank_loss": blue_loses_rank,
                "red_implication": red_implication,
                "blue_implication": blue_implication,
                "title_shot_phrase": title_shot_phrase,
                "title_fight_phrase": title_fight_phrase,
                "champion_name": champion_name,
                "is_vacant": is_vacant,
            }
        except Exception as e:
            print(f"[api.get_fight_stakes] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_fight_fan_pulse(self, fight_id):
        """Return fan-pulse data for a booked fight.

        Used by the Fan Pulse modal. Mines:
          - Rivalry context (if these two have fought before)
          - Hometown reaction (if a fighter is fighting in their
            home region)
          - Voice-layer reaction phrases
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            fid = int(fight_id or 0)
            if not fid:
                return {"ok": False, "error": "Missing fight_id."}

            f_row = conn.execute(
                "SELECT f.event_id, f.weight_class_id, "
                "fpa.fighter_id AS red_id, "
                "fpb.fighter_id AS blue_id "
                "FROM fights f "
                "JOIN fight_participants fpa "
                "  ON fpa.fight_id=f.fight_id AND fpa.corner='red' "
                "JOIN fight_participants fpb "
                "  ON fpb.fight_id=f.fight_id AND fpb.corner='blue' "
                "WHERE f.fight_id=?",
                (fid,),
            ).fetchone()
            if not f_row:
                return {"ok": False, "error": "Fight not found."}
            (eid, wc_id, red_id, blue_id) = f_row

            # Verify event belongs to player's promo.
            ev_row = conn.execute(
                "SELECT promotion_id, venue_id FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row or ev_row[0] != pid:
                return {"ok": False,
                        "error": "This fight belongs to another promotion."}
            venue_id = ev_row[1]

            red_brief = self._fighter_brief(conn, red_id) or {}
            blue_brief = self._fighter_brief(conn, blue_id) or {}

            # --- Rivalry context (have they fought before?) ---
            prev_meetings = conn.execute(
                "SELECT COUNT(*) FROM fight_history "
                "WHERE fighter_id=? AND opponent_id=?",
                (red_id, blue_id),
            ).fetchone()
            n_meetings = int(prev_meetings[0] or 0) if prev_meetings else 0
            # Check for an active rivalry row.
            rivalry_row = conn.execute(
                "SELECT rivalry_heat, rivalry_type, "
                "fighter_a_wins, fighter_b_wins, draws, "
                "origin_description "
                "FROM rivalries "
                "WHERE is_active=1 AND "
                "((fighter_a_id=? AND fighter_b_id=?) OR "
                " (fighter_a_id=? AND fighter_b_id=?))",
                (red_id, blue_id, blue_id, red_id),
            ).fetchone()
            rivalry_phrase = None
            series_phrase = None
            if rivalry_row:
                (heat, rtype, a_wins, b_wins, draws, origin) = rivalry_row
                # Determine who is who in the rivalry row.
                if rivalry_row:
                    # Need to fetch fighter_a_id to know which fighter
                    # the a_wins belongs to.
                    pass
                # Get the rivalry IDs to know which side is which.
                riv_ids = conn.execute(
                    "SELECT fighter_a_id, fighter_b_id FROM rivalries "
                    "WHERE is_active=1 AND "
                    "((fighter_a_id=? AND fighter_b_id=?) OR "
                    " (fighter_a_id=? AND fighter_b_id=?))",
                    (red_id, blue_id, blue_id, red_id),
                ).fetchone()
                if riv_ids:
                    a_id, b_id = riv_ids
                    red_wins = a_wins if a_id == red_id else b_wins
                    blue_wins = b_wins if b_id == blue_id else a_wins
                    if red_wins == blue_wins:
                        series_phrase = (
                            f"Series tied {red_wins}-{blue_wins} "
                            f"(+{draws} draw{'s' if draws != 1 else ''})."
                        )
                    else:
                        leader = (red_brief.get('name', 'Red')
                                  if red_wins > blue_wins
                                  else blue_brief.get('name', 'Blue'))
                        series_phrase = (
                            f"{leader} leads the series "
                            f"{max(red_wins, blue_wins)}-"
                            f"{min(red_wins, blue_wins)}."
                        )
                # Rivalry heat phrase.
                if heat >= 75:
                    rivalry_phrase = (
                        "Bad blood — these two have history. The crowd "
                        "will be electric."
                    )
                elif heat >= 50:
                    rivalry_phrase = (
                        "There's a rivalry brewing here — fans remember "
                        "the last meeting."
                    )
                elif heat >= 25:
                    rivalry_phrase = (
                        "A mild grudge from past encounters adds spice."
                    )
            elif n_meetings > 0:
                # They've fought before but no active rivalry row.
                series_phrase = (
                    f"These two have met {n_meetings} time"
                    f"{'s' if n_meetings != 1 else ''} before."
                )

            # --- Hometown reaction ---
            # Check if either fighter is from the event venue's nation.
            hometown_phrases = []
            venue_row = conn.execute(
                "SELECT n.nation_id, n.name, c.name "
                "FROM venues v "
                "JOIN cities c ON c.city_id=v.city_id "
                "LEFT JOIN nations n ON n.nation_id=c.nation_id "
                "WHERE v.venue_id=?",
                (venue_id,),
            ).fetchone()
            venue_nation_id = venue_nation_id_ = venue_nation_name = None
            venue_city_name = None
            if venue_row:
                venue_nation_id, venue_nation_name, venue_city_name = venue_row
            for brief, color in ((red_brief, 'red'), (blue_brief, 'blue')):
                fid_check = brief.get('fighter_id')
                if not fid_check:
                    continue
                f_row = conn.execute(
                    "SELECT f.birth_nation_id, f.birth_city_id, "
                    "n1.name AS birth_nation, "
                    "n2.name AS residence_nation "
                    "FROM fighters f "
                    "LEFT JOIN nations n1 "
                    "  ON n1.nation_id=f.birth_nation_id "
                    "LEFT JOIN nations n2 "
                    "  ON n2.nation_id=f.residence_nation_id "
                    "WHERE f.fighter_id=?",
                    (fid_check,),
                ).fetchone()
                if not f_row:
                    continue
                (birth_nation_id, birth_city_id, birth_nation,
                 residence_nation) = f_row
                name = brief.get('name', 'Fighter')
                if (venue_nation_id and birth_nation_id
                        and venue_nation_id == birth_nation_id):
                    hometown_phrases.append({
                        "corner": color,
                        "fighter_name": name,
                        "phrase": (
                            f"{name} fights on home soil — the crowd "
                            f"will be squarely in {brief.get('gender', 'their') == 'female' and 'her' or 'his'} corner."
                        ),
                    })

            # --- Voice-layer fan reaction ---
            # Combine signals into a single "fan pulse" verdict.
            matchup_score = 0.0
            try:
                red_dict = _build_fighter_dict_for_matchup(conn, red_id) or {}
                blue_dict = _build_fighter_dict_for_matchup(conn, blue_id) or {}
                matchup_score = _compute_matchup_score(
                    conn, red_dict, blue_dict,
                )
            except Exception:
                pass
            if matchup_score >= 75 and (rivalry_row or n_meetings > 0):
                fan_pulse_phrase = (
                    "Fans have been waiting for this one — a marquee "
                    "matchup with a backstory."
                )
            elif matchup_score >= 65:
                fan_pulse_phrase = (
                    "Buzz is building — this is the kind of fight that "
                    "sells tickets."
                )
            elif matchup_score >= 45:
                fan_pulse_phrase = (
                    "Solid fan interest — neither man is a household name, "
                    "but the matchup is intriguing."
                )
            elif rivalry_row or n_meetings > 0:
                fan_pulse_phrase = (
                    "The storyline carries this one — fans want to see "
                    "how the chapter ends."
                )
            else:
                fan_pulse_phrase = (
                    "Quiet interest — this fight is flying under the radar."
                )

            return {
                "ok": True,
                "fight_id": fid,
                "event_id": eid,
                "red_fighter": red_brief,
                "blue_fighter": blue_brief,
                "n_previous_meetings": n_meetings,
                "rivalry_phrase": rivalry_phrase,
                "series_phrase": series_phrase,
                "hometown_phrases": hometown_phrases,
                "fan_pulse_phrase": fan_pulse_phrase,
                "matchup_score": round(matchup_score, 1),
            }
        except Exception as e:
            print(f"[api.get_fight_fan_pulse] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_fight_compare(self, fight_id):
        """Return radar-chart data for a booked fight.

        Used by the Compare modal. Returns both fighters' 25 attributes
        + the punditry analysis (predicted winner, style edge, etc.).
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            fid = int(fight_id or 0)
            if not fid:
                return {"ok": False, "error": "Missing fight_id."}

            f_row = conn.execute(
                "SELECT f.event_id, "
                "fpa.fighter_id AS red_id, "
                "fpb.fighter_id AS blue_id "
                "FROM fights f "
                "JOIN fight_participants fpa "
                "  ON fpa.fight_id=f.fight_id AND fpa.corner='red' "
                "JOIN fight_participants fpb "
                "  ON fpb.fight_id=f.fight_id AND fpb.corner='blue' "
                "WHERE f.fight_id=?",
                (fid,),
            ).fetchone()
            if not f_row:
                return {"ok": False, "error": "Fight not found."}
            (eid, red_id, blue_id) = f_row
            # Verify event belongs to player's promo.
            ev_row = conn.execute(
                "SELECT promotion_id FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row or ev_row[0] != pid:
                return {"ok": False,
                        "error": "This fight belongs to another promotion."}

            red_brief = self._fighter_brief(conn, red_id) or {}
            blue_brief = self._fighter_brief(conn, blue_id) or {}

            # Phase 6 / Task B1 — voice-compliant radar chart data.
            # Was: _fighter_attributes_dict(conn, fighter_id) which
            # returned the 26 raw 0-100 attribute ints (§14 violation
            # — the radar polygon revealed relative attribute
            # magnitudes). Now we route through
            # fighter_descriptors.attribute_descriptors (JSON of voice
            # phrases) and compute a tier pct per phrase (gold=100,
            # steel=60, crimson=25) so the polygon shape still conveys
            # "striker vs grappler" relative style without leaking
            # raw attribute numbers.
            (red_phrases, red_tiers) = _attribute_phrase_dicts(conn, red_id)
            (blue_phrases, blue_tiers) = _attribute_phrase_dicts(conn, blue_id)

            # Reuse get_fight_analysis for the punditry take.
            analysis_resp = self.get_fight_analysis(red_id, blue_id)
            analysis = analysis_resp.get("analysis", {}) if analysis_resp.get("ok") else {}

            return {
                "ok": True,
                "fight_id": fid,
                "event_id": eid,
                "red_fighter": red_brief,
                "blue_fighter": blue_brief,
                # Phase 6 / Task B1 — voice-compliant radar data.
                # red_attribute_phrases/blue_attribute_phrases: voice
                #   phrases per attribute (from fighter_descriptors).
                # red_attribute_tiers/blue_attribute_tiers: tier pct
                #   (100 gold / 60 steel / 25 crimson) — drives the
                #   radar polygon point radius. NO raw 0-100 attribute
                #   ints are returned to JS anymore.
                "red_attribute_phrases": red_phrases,
                "blue_attribute_phrases": blue_phrases,
                "red_attribute_tiers": red_tiers,
                "blue_attribute_tiers": blue_tiers,
                "analysis": analysis,
            }
        except Exception as e:
            print(f"[api.get_fight_compare] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def _fighter_attributes_dict(self, conn, fighter_id):
        """Return a dict of {attr_name: value} for the 26 attributes.

        DEPRECATED (Phase 6 / Task B1) — was used by get_fight_compare
        to feed the radar chart with raw 0-100 attribute ints. The
        radar chart now reads voice phrases + tier pct from
        fighter_descriptors.attribute_descriptors via
        _attribute_phrase_dicts(). Kept here as a private helper for
        internal/server-side computations that may still need the raw
        values (e.g. matchup scoring); NEVER expose the returned dict
        to the JS layer.
        """
        if not fighter_id:
            return {}
        cols_sql = ", ".join(_FIGHTER_ATTR_COLUMNS)
        row = conn.execute(
            f"SELECT {cols_sql} FROM fighter_attributes WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        if not row:
            return {name: 50 for name in _FIGHTER_ATTR_COLUMNS}
        return {name: (val if val is not None else 50)
                for name, val in zip(_FIGHTER_ATTR_COLUMNS, row)}

    def estimate_signing_cost(self, fighter_id):
        """Return estimated signing cost as {cost_display, cost_value}.

        Per NAV_BUTTONS_AUDIT §3.2: derived from potential + age +
        momentum + market. The raw potential int is NEVER sent to JS —
        only the formatted cost.

        Formula (server-side only):
          base = $25K
          potential_factor = (potential / 100) ^ 2 * $500K  (high-potential = expensive)
          age_factor = age <= 24 ? 1.5x : age <= 30 ? 1.2x : age <= 35 ? 0.8x : 0.4x
          momentum_factor = very_high ? 1.4x : high ? 1.2x : stable ? 1.0x
                            : falling ? 0.8x : collapsing ? 0.6x
          cost = base + potential_factor * age_factor * momentum_factor
        """
        try:
            fid = int(fighter_id)
            conn = self.conn
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None

            f = conn.execute(
                "SELECT f.date_of_birth, fc.potential, fd.momentum_short "
                "FROM fighters f "
                "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id = f.fighter_id "
                "WHERE f.fighter_id=?",
                (fid,),
            ).fetchone()
            if not f:
                return {"cost_display": "—", "cost_value": 0}

            age = _compute_age(f[0], sim_date)
            potential = f[1] or 50
            momentum_label = _decode_label(f[2]) if f[2] else "stable"

            base = 25_000
            potential_factor = ((potential / 100.0) ** 2) * 500_000

            if age <= 24:
                age_mult = 1.5
            elif age <= 30:
                age_mult = 1.2
            elif age <= 35:
                age_mult = 0.8
            else:
                age_mult = 0.4

            mom_map = {
                "very_high": 1.4, "high": 1.2, "stable": 1.0,
                "falling": 0.8, "collapsing": 0.6,
            }
            mom_mult = mom_map.get(momentum_label, 1.0)

            cost = base + potential_factor * age_mult * mom_mult
            cost = max(10_000, int(cost))  # floor at $10K

            return {
                "cost_display": _format_cash(cost),
                "cost_value": cost,
                "fighter_id": fid,
            }
        except Exception as e:
            print(f"[api.estimate_signing_cost] {e}", flush=True)
            return {"cost_display": "—", "cost_value": 0, "error": str(e)}

    def sign_free_agent(self, fighter_id, salary=None, signing_bonus=0,
                        contract_length=2, win_bonus_pct=0.5):
        """Sign a free agent to the player's promotion with player-set
        contract terms (Phase E3.3 — Negotiation).

        Wraps services.contracts.sign_free_agent with auto-filled:
          - promotion_id from get_player_promotion()
          - start_date from get_clock()
          - salary: player-set (from negotiation slider), OR fall back
            to estimate_signing_cost() if None (backward compat for
            pre-E3 callers).

        Phase E3.3 changes:
          - salary, signing_bonus, contract_length, win_bonus_pct now
            player-set via the negotiation panel in free_agents.js.
          - signing_bonus is deducted from promo cash immediately
            (finance_transactions row, type='signing_bonus', negative).
            'signing_bonus' was already in the CHECK constraint.
          - contract end_date = start_date + contract_length years
            (was: +365 days fixed in services.contracts.sign_free_agent).
            Done via a direct contracts UPDATE after the service call
            so we don't have to modify services/contracts.py (which
            would break the rival AI's signing path).
          - win_bonus_pct stored as JSON in contracts.bonus_structure:
            {"win_bonus_pct": <float 0-1>}. finance._parse_win_bonus_pct
            already supports this format (Phase E2.5).

        PHASE-R (Reward Layer §6 Principle 4): also writes a row to
        the player_decisions log so the signing "echoes" later on the
        Dashboard + Fighter Profile. Stores the signing cost +
        contract_id in context_json so echoes_engine can quote
        specifics ("signed for $120K") without re-querying.

        Returns {ok, fighter_id, contract_id, cost_value, cost_display,
                 signing_bonus, contract_length, win_bonus_pct}.
        """
        try:
            fid = int(fighter_id)
            conn = self.conn
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}

            clock = get_clock(conn)
            start_date = clock[0] if clock else None
            if not start_date:
                return {"ok": False, "error": "No sim clock available."}

            # If salary not provided (legacy caller), fall back to the
            # estimate_signing_cost formula. Phase E3 callers always
            # pass salary explicitly (the negotiation slider value).
            if salary is None:
                cost = self.estimate_signing_cost(fid)
                salary = float(cost.get("cost_value", 50000))
            else:
                salary = float(salary)
            # Defensive clamps.
            salary = max(10000, min(500000, salary))
            signing_bonus = float(signing_bonus or 0)
            signing_bonus = max(0, min(1_000_000, signing_bonus))
            contract_length = int(contract_length or 2)
            contract_length = max(1, min(5, contract_length))
            win_bonus_pct = float(win_bonus_pct if win_bonus_pct is not None else 0.5)
            win_bonus_pct = max(0.0, min(1.0, win_bonus_pct))

            # HW1.3 (Hardening_Phase.md §HW1.3 / CRITICAL #3) — wire
            # economic causality into the player's sign_free_agent
            # path. Before this check, the player could sign any free
            # agent for any signing_bonus + salary regardless of
            # current_cash — the deduction would push current_cash
            # negative and the bankruptcy pathway in reputation.py
            # would eventually fire. The check refuses the signing
            # when the player can't afford the immediate cash hit
            # (signing_bonus) PLUS the first-year salary commitment
            # (the minimum cash reserve the player needs to actually
            # pay the fighter through their first year).
            #
            # The threshold is signing_bonus + (salary / 12) — the
            # signing bonus is paid immediately, and one month of
            # salary is the minimum reserve needed to keep the
            # fighter on the roster past the first pay cycle. We do
            # NOT require the full salary × contract_length in cash
            # (that would be too strict — revenue from events is
            # expected to cover ongoing salary).
            cash_row = conn.execute(
                "SELECT current_cash, financial_state FROM promotions "
                "WHERE promotion_id=?",
                (pid,),
            ).fetchone()
            current_cash = float(cash_row[0]) if cash_row and cash_row[0] is not None else 0.0
            promo_financial_state = (cash_row[1] if cash_row else None) or 'HEALTHY'

            # HW1.4 (Hardening_Phase.md §HW1.4 / CRITICAL #4) — when
            # the promo is in CRISIS state (cash < 0 for 1+ months),
            # all FA signings are FROZEN. The player must trade their
            # way out of crisis, not sign their way out. This makes
            # the financial state machine consequential: PRESSURED =
            # -10% marketing; STRUGGLING = release 1 staff; CRISIS =
            # no new signings.
            if promo_financial_state == 'CRISIS':
                return {
                    "ok": False,
                    "blocked_by_crisis": True,
                    "financial_state": promo_financial_state,
                    "error": (
                        "Free agent signings are frozen — your promotion "
                        "is in financial CRISIS (cash has been negative "
                        "for at least one month). Run a show, release "
                        "payroll, or wait for the bankruptcy pathway "
                        "to fire and reset cash."
                    ),
                }

            first_month_salary = salary / 12.0
            required_cash = signing_bonus + first_month_salary
            if current_cash < required_cash:
                return {
                    "ok": False,
                    "blocked_by_affordability": True,
                    "current_cash": current_cash,
                    "current_cash_display": _format_cash(current_cash),
                    "required_cash": required_cash,
                    "required_cash_display": _format_cash(required_cash),
                    "signing_bonus": signing_bonus,
                    "signing_bonus_display": _format_cash(signing_bonus),
                    "first_month_salary": first_month_salary,
                    "first_month_salary_display": _format_cash(first_month_salary),
                    "error": (
                        f"Insufficient cash — you need at least "
                        f"{_format_cash(required_cash)} "
                        f"(signing bonus + first month salary) but only "
                        f"have {_format_cash(current_cash)}. Run a show "
                        f"or release a fighter to free up cash."
                    ),
                }

            # PHASE M3.2: if there's a pending bidding_alert for this
            # fighter, block the direct sign_free_agent — the player
            # MUST use counter_offer instead. This forces the player
            # into the bidding-war resolution flow (rival AI's offer
            # competes against the player's offer based on the unified
            # formula). Without this block, the player could bypass
            # the bidding war by signing directly.
            alert_row = conn.execute(
                "SELECT alert_id, rival_promo_id, offered_salary "
                "FROM bidding_alerts "
                "WHERE fighter_id=? AND status='pending' "
                "ORDER BY alert_id DESC LIMIT 1",
                (fid,),
            ).fetchone()
            if alert_row:
                (alert_id, rival_pid, rival_salary) = alert_row
                rival_name_row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id=?",
                    (rival_pid,),
                ).fetchone()
                rival_name = (rival_name_row[0] if rival_name_row
                              else f"Promo {rival_pid}")
                return {
                    "ok": False,
                    "blocked_by_bidding_alert": True,
                    "alert_id": alert_id,
                    "rival_promo_id": rival_pid,
                    "rival_promo_name": rival_name,
                    "rival_offered_salary": float(rival_salary or 0),
                    "rival_offered_salary_display": _format_cash(
                        float(rival_salary or 0)) + "/yr",
                    "error": (
                        f"{rival_name} is pursuing this fighter — use "
                        f"Counter Offer to compete in the bidding war "
                        f"instead of signing directly."
                    ),
                }

            from services.contracts import sign_free_agent as _sign
            from services.contracts import get_roster_cap, get_roster_count
            # RESEED Step 10 — pre-check roster cap so we can return a
            # clean error message (services.contracts.sign_free_agent
            # also enforces the cap, but its error is generic).
            cap = get_roster_cap(conn, pid)
            current_count = get_roster_count(conn, pid)
            if current_count >= cap:
                return {
                    "ok": False,
                    "error": (
                        f"Roster is full ({current_count}/{cap}). "
                        f"Release a fighter to make room."
                    ),
                }
            contract_id = _sign(conn, fid, pid, start_date, salary=salary)
            if not contract_id:
                return {"ok": False, "error": "Sign failed — fighter may already be signed or retired."}

            # Phase E3.3: override the contract end_date to use the
            # player-set contract_length (services.contracts defaults
            # to +365 days; we want +N years). Also store the
            # win_bonus_pct in bonus_structure (JSON) so Phase E2.5's
            # _parse_win_bonus_pct picks it up when computing purses.
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                # Add contract_length years (handle Feb 29 by falling
                # back to Feb 28 if the target year isn't a leap year).
                end_year = start_dt.year + contract_length
                try:
                    end_dt = start_dt.replace(year=end_year)
                except ValueError:
                    # Feb 29 in a non-leap target year → use Feb 28.
                    end_dt = start_dt.replace(year=end_year, day=28)
                end_date = end_dt.strftime("%Y-%m-%d")
                bonus_struct = json.dumps({
                    "win_bonus_pct": win_bonus_pct,
                })
                conn.execute(
                    "UPDATE contracts SET end_date=?, bonus_structure=? "
                    "WHERE contract_id=?",
                    (end_date, bonus_struct, contract_id),
                )
            except Exception as e:
                print(f"[app_web.sign_free_agent] WARN: contract term "
                      f"override failed (defaulting to 365d): {e}",
                      flush=True)

            # Phase E3.3: deduct signing_bonus from promo cash immediately
            # if the player offered one. Write a finance_transactions
            # row (type='signing_bonus', negative). The _record_transaction
            # helper in finance.py updates current_cash + writes the row
            # in one step — but to avoid the import dance we inline the
            # two SQL statements (matches the pattern in finance.py).
            if signing_bonus > 0:
                conn.execute(
                    "INSERT INTO finance_transactions (promotion_id, "
                    "event_id, fighter_id, transaction_type, amount, "
                    "description, transaction_date) "
                    "VALUES (?, NULL, ?, 'signing_bonus', ?, ?, ?)",
                    (pid, fid, -signing_bonus,
                     f"signing bonus ({_format_cash(signing_bonus)})",
                     start_date),
                )
                conn.execute(
                    "UPDATE promotions SET current_cash = current_cash + ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE promotion_id = ?",
                    (-signing_bonus, pid),
                )

            # PHASE-R: log the signing decision so it can echo later.
            try:
                from player_decisions import log_decision, TYPE_SIGN
                log_decision(
                    conn, TYPE_SIGN,
                    target_fighter_id=fid,
                    target_promo_id=pid,
                    context={
                        "contract_id": contract_id,
                        "cost_value": salary,
                        "cost_display": _format_cash(salary),
                        "signing_bonus": signing_bonus,
                        "signing_bonus_display": _format_cash(signing_bonus),
                        "contract_length_years": contract_length,
                        "win_bonus_pct": win_bonus_pct,
                        "start_date": start_date,
                        "total_value": salary * contract_length + signing_bonus,
                    },
                    decision_date=start_date,
                )
            except Exception as e:
                print(f"[app_web.sign_free_agent] WARN: log_decision "
                      f"failed: {e}", flush=True)

            conn.commit()
            return {
                "ok": True,
                "fighter_id": fid,
                "contract_id": contract_id,
                "cost_value": salary,
                "cost_display": _format_cash(salary),
                "signing_bonus": signing_bonus,
                "signing_bonus_display": _format_cash(signing_bonus),
                "contract_length": contract_length,
                "win_bonus_pct": win_bonus_pct,
            }
        except Exception as e:
            print(f"[api.sign_free_agent] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # BIDDING WARS — Phase M3.2 (docs/MASTER_PLAN_MATCHMAKING.md §2.2)
    # ============================================================

    def get_bidding_alerts(self):
        """Return the list of active SIGNING_INTENT alerts for the player.

        Per Phase M3.2: surfaces rival AI signing intents the player
        can counter-offer against. Each alert represents a free agent
        a rival promo is pursuing — the player has decision_window_days
        to make a counter-offer via counter_offer() before the rival AI
        signs the fighter.

        Returns only 'pending' alerts whose fighter is still a free
        agent. Resolved alerts (won_by_player / won_by_rival /
        lost_race) are not surfaced — the player sees them as news
        items instead.

        Voice compliance (CONVENTIONS §14): no raw potential /
        realization numbers in the payload — only salary in $K/M format
        + voice phrases for promo size_tier fit. The fighter's
        ceiling_phrase comes from fighter_descriptors (already voice-
        layer).

        Returns: {
          alerts: [
            {
              alert_id, fighter_id, fighter_name,
              rival_promo_id, rival_promo_name, rival_promo_size_tier,
              offered_salary, offered_salary_display,
              days_remaining, intent_date, expiry_date,
              fighter_ceiling_phrase,  # voice phrase from descriptors
              fighter_weight_class_name, fighter_record_str,
              fighter_age, fighter_nickname
            }, ...
          ],
          count: int
        }
        """
        try:
            conn = self.conn
            clock = get_clock(conn)
            sim_date = clock[0] if clock else None
            if not sim_date:
                return {"alerts": [], "count": 0}

            rows = conn.execute(
                "SELECT ba.alert_id, ba.fighter_id, ba.rival_promo_id, "
                "       ba.offered_salary, ba.intent_date, "
                "       ba.expiry_date, ba.decision_window_days, "
                "       f.first_name, f.last_name, f.nickname, "
                "       f.weight_class_id, f.date_of_birth, "
                "       fc.record_wins, fc.record_losses, "
                "       p.name AS rival_promo_name, p.size_tier, "
                "       wc.name AS wc_name "
                "FROM bidding_alerts ba "
                "JOIN fighters f ON f.fighter_id = ba.fighter_id "
                "LEFT JOIN fighter_career fc "
                "       ON fc.fighter_id = ba.fighter_id "
                "JOIN promotions p ON p.promotion_id = ba.rival_promo_id "
                "LEFT JOIN weight_classes wc "
                "       ON wc.weight_class_id = f.weight_class_id "
                "WHERE ba.status = 'pending' "
                "  AND f.current_promotion_id IS NULL "
                "  AND f.is_active = 1 "
                "  AND f.is_retired = 0 "
                "  AND ba.expiry_date >= ? "
                "ORDER BY ba.expiry_date ASC",
                (sim_date,),
            ).fetchall()

            alerts = []
            for r in rows:
                (alert_id, fighter_id, rival_promo_id, offered_salary,
                 intent_date, expiry_date, window_days,
                 fn, ln, nick, wc_id, dob,
                 wins, losses, rival_name, size_tier, wc_name) = r
                # Compute days remaining (inclusive — expiry day counts
                # as the last day the player can respond).
                try:
                    sim_dt = datetime.strptime(sim_date, "%Y-%m-%d")
                    exp_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
                    days_remaining = max(
                        0, (exp_dt - sim_dt).days + 1
                    )
                except (ValueError, TypeError):
                    days_remaining = 0
                # Compute fighter age (for display).
                age = None
                if dob:
                    try:
                        dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                        sim_dt2 = datetime.strptime(sim_date, "%Y-%m-%d")
                        age = sim_dt2.year - dob_dt.year
                        if (sim_dt2.month, sim_dt2.day) < (dob_dt.month, dob_dt.day):
                            age -= 1
                    except (ValueError, TypeError):
                        pass
                # Ceiling voice phrase from fighter_descriptors (if
                # available — falls back to "Unscouted").
                ceiling_phrase = "Unscouted"
                try:
                    desc_row = conn.execute(
                        "SELECT ceiling_phrase FROM fighter_descriptors "
                        "WHERE fighter_id=?",
                        (fighter_id,),
                    ).fetchone()
                    if desc_row and desc_row[0]:
                        ceiling_phrase = desc_row[0]
                except Exception:
                    pass
                # Size-tier voice phrase (e.g., 'major' → "Major League Powerhouse").
                size_tier_phrase = _size_tier_phrase(size_tier)

                record_str = f"{wins or 0}-{losses or 0}"
                alerts.append({
                    "alert_id": alert_id,
                    "fighter_id": fighter_id,
                    "fighter_name": f"{fn} {ln}".strip(),
                    "fighter_nickname": nick or "",
                    "rival_promo_id": rival_promo_id,
                    "rival_promo_name": rival_name or f"Promo {rival_promo_id}",
                    "rival_promo_size_tier": size_tier or "small",
                    "rival_promo_size_tier_phrase": size_tier_phrase,
                    "offered_salary": float(offered_salary or 0),
                    "offered_salary_display": _format_cash(
                        float(offered_salary or 0)) + "/yr",
                    "days_remaining": int(days_remaining),
                    "decision_window_days": int(window_days),
                    "intent_date": intent_date,
                    "expiry_date": expiry_date,
                    "fighter_ceiling_phrase": ceiling_phrase,
                    "fighter_weight_class_name": wc_name or "—",
                    "fighter_record_str": record_str,
                    "fighter_age": age,
                })
            return {"alerts": alerts, "count": len(alerts)}
        except Exception as e:
            print(f"[api.get_bidding_alerts] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"alerts": [], "count": 0, "error": str(e)}

    def counter_offer(self, fighter_id, salary, signing_bonus=0,
                      contract_length=2, win_bonus_pct=0.5):
        """Player's counter-offer against a rival AI's SIGNING_INTENT.

        Per Phase M3.2 (docs/MASTER_PLAN_MATCHMAKING.md §2.2 step 3):
          1. Look up the pending bidding_alert for fighter_id.
          2. If not found / expired / fighter no longer FA: return error.
          3. Compute the player's offer_score using the unified formula
             (reputation + salary + signing_bonus + size_tier fit +
             realization-weighted potential). The rival AI's offer_score
             is already stored on the alert.
          4. The fighter chooses the higher score (with ±5% randomness
             for drama — close bids aren't deterministic).
          5. The winner signs via sign_free_agent (player's promo) OR
             sign_free_agent (rival promo) — depending on the winner.
          6. Update the alert status ('won_by_player' / 'won_by_rival')
             + record the player's offer details for audit.
          7. Return {accepted, chosen_promo_id, reason, ...}.

        The player's signing still goes through the existing
        sign_free_agent path (which writes the FIGHTER_SIGNED event +
        deducts the signing_bonus + logs the player_decisions row). The
        rival AI's signing uses the same sign_free_agent with the
        rival_promo_id.

        Args:
          fighter_id: int
          salary: float — player's offered annual salary ($/yr)
          signing_bonus: float — player's offered upfront bonus
          contract_length: int — years (1-5). Only used if the player
            wins (rival AI signing uses the rival AI's stored salary).
          win_bonus_pct: float — 0-1. Only used if the player wins.

        Returns:
          {
            ok: bool,
            accepted: bool,           # True iff player won the bid
            chosen_promo_id: int,     # 1 (player) or rival_promo_id
            chosen_promo_name: str,
            reason: str,              # voice-phrase explanation
            fighter_id: int,
            fighter_name: str,
            player_offer_score: float,
            rival_offer_score: float,
            # If player won: contract details (mirrors sign_free_agent).
            contract_id: int,         # only if accepted
            cost_value: float,
            cost_display: str,
            signing_bonus: float,
            signing_bonus_display: str,
            contract_length: int,
            win_bonus_pct: float,
          }
        """
        try:
            fid = int(fighter_id)
            salary = float(salary or 0)
            signing_bonus = float(signing_bonus or 0)
            contract_length = int(contract_length or 2)
            win_bonus_pct = float(win_bonus_pct if win_bonus_pct is not None else 0.5)
            # Defensive clamps (mirror sign_free_agent).
            salary = max(10000, min(500000, salary))
            signing_bonus = max(0, min(1_000_000, signing_bonus))
            contract_length = max(1, min(5, contract_length))
            win_bonus_pct = max(0.0, min(1.0, win_bonus_pct))

            conn = self.conn
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "accepted": False,
                        "error": "No player promotion selected.",
                        "reason": "You haven't selected a promotion yet."}

            clock = get_clock(conn)
            sim_date = clock[0] if clock else None
            if not sim_date:
                return {"ok": False, "accepted": False,
                        "error": "No sim clock available."}

            # Look up the pending alert for this fighter.
            row = conn.execute(
                "SELECT alert_id, rival_promo_id, offered_salary, "
                "       offer_score, expiry_date, status "
                "FROM bidding_alerts "
                "WHERE fighter_id=? AND status='pending' "
                "ORDER BY alert_id DESC LIMIT 1",
                (fid,),
            ).fetchone()
            if not row:
                return {"ok": False, "accepted": False,
                        "error": "No active bidding alert for this fighter.",
                        "reason": ("There's no active rival interest in this "
                                   "fighter right now. You can sign him "
                                   "directly via the Free Agents screen.")}
            (alert_id, rival_pid, rival_salary, rival_score,
             expiry_date, status) = row

            # Verify the fighter is still a FA (defensive).
            fa_row = conn.execute(
                "SELECT current_promotion_id, is_active, is_retired, "
                "       first_name, last_name "
                "FROM fighters WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if (not fa_row or fa_row[0] is not None
                    or not fa_row[1] or fa_row[2]):
                # Mark the alert lost_race + return error.
                conn.execute(
                    "UPDATE bidding_alerts SET status='lost_race', "
                    "resolved_date=? WHERE alert_id=?",
                    (sim_date, alert_id),
                )
                conn.commit()
                return {"ok": False, "accepted": False,
                        "error": "Fighter is no longer a free agent.",
                        "reason": "He's already signed elsewhere."}
            fighter_name = f"{fa_row[3]} {fa_row[4]}".strip()

            # Compute both offers' desirability scores using the
            # UNIFIED formula (what the FIGHTER cares about: reputation,
            # salary, signing_bonus, size_tier fit, effective_ceiling).
            # The stored rival offer_score is the rival AI's INTERNAL
            # evaluation (which fighter to pursue) — NOT what the
            # fighter cares about. We recompute the rival's desirability
            # using the same formula as the player's so the comparison
            # is fair.
            player_score = self._compute_fighter_desirability(
                pid, fid, salary, signing_bonus, conn,
            )
            rival_desirability = self._compute_fighter_desirability(
                rival_pid, fid, rival_salary, 0.0, conn,
            )

            # ±5% randomness for drama (close bids aren't deterministic).
            import random as _rng
            player_final = player_score * (1.0 + _rng.uniform(-0.05, 0.05))
            rival_final = rival_desirability * (1.0 + _rng.uniform(-0.05, 0.05))
            player_won = player_final >= rival_final

            # Resolve — sign the fighter with the winner.
            from services.contracts import sign_free_agent as _sign
            if player_won:
                # Player wins — sign to the player's promo at the
                # player's offered salary. Mirror sign_free_agent's
                # contract-end-date override + signing_bonus deduction
                # + player_decisions log (the _sign helper does the
                # core sign; we layer on the E3.3 enhancements).
                contract_id = _sign(
                    conn, fid, pid, sim_date, salary=salary,
                )
                if not contract_id:
                    return {"ok": False, "accepted": False,
                            "error": "Sign failed.",
                            "reason": ("The deal collapsed at the last "
                                       "minute — try again.")}
                # Override end_date to use contract_length (years, not
                # the default 365 days). Mirror sign_free_agent.
                try:
                    start_dt = datetime.strptime(sim_date, "%Y-%m-%d")
                    end_year = start_dt.year + contract_length
                    try:
                        end_dt = start_dt.replace(year=end_year)
                    except ValueError:
                        end_dt = start_dt.replace(year=end_year, day=28)
                    end_date = end_dt.strftime("%Y-%m-%d")
                    bonus_struct = json.dumps(
                        {"win_bonus_pct": win_bonus_pct}
                    )
                    conn.execute(
                        "UPDATE contracts SET end_date=?, bonus_structure=? "
                        "WHERE contract_id=?",
                        (end_date, bonus_struct, contract_id),
                    )
                except Exception as e:
                    print(f"[counter_offer] WARN: contract term override "
                          f"failed: {e}", flush=True)
                # Deduct signing_bonus from promo cash.
                if signing_bonus > 0:
                    conn.execute(
                        "INSERT INTO finance_transactions (promotion_id, "
                        "event_id, fighter_id, transaction_type, amount, "
                        "description, transaction_date) "
                        "VALUES (?, NULL, ?, 'signing_bonus', ?, ?, ?)",
                        (pid, fid, -signing_bonus,
                         f"signing bonus ({_format_cash(signing_bonus)}) "
                         f"[bidding war win]",
                         sim_date),
                    )
                    conn.execute(
                        "UPDATE promotions SET current_cash = current_cash + ?, "
                        "updated_at = CURRENT_TIMESTAMP "
                        "WHERE promotion_id = ?",
                        (-signing_bonus, pid),
                    )
                # Log the player_decisions row (TYPE_SIGN).
                try:
                    from player_decisions import log_decision, TYPE_SIGN
                    log_decision(
                        conn, TYPE_SIGN,
                        target_fighter_id=fid,
                        target_promo_id=pid,
                        context={
                            "contract_id": contract_id,
                            "cost_value": salary,
                            "cost_display": _format_cash(salary),
                            "signing_bonus": signing_bonus,
                            "signing_bonus_display": _format_cash(signing_bonus),
                            "contract_length_years": contract_length,
                            "win_bonus_pct": win_bonus_pct,
                            "start_date": sim_date,
                            "bidding_war_win": True,
                            "rival_promo_id": rival_pid,
                            "rival_offer_score": float(rival_score),
                            "player_offer_score": float(player_score),
                        },
                        decision_date=sim_date,
                    )
                except Exception as e:
                    print(f"[counter_offer] WARN: log_decision failed: "
                          f"{e}", flush=True)
                # Update the alert.
                conn.execute(
                    "UPDATE bidding_alerts SET status='won_by_player', "
                    "player_offer_salary=?, player_offer_bonus=?, "
                    "player_offer_score=?, resolved_date=? "
                    "WHERE alert_id=?",
                    (salary, signing_bonus, player_score,
                     sim_date, alert_id),
                )
                # Write a "you won X" news item for the player.
                rival_name_row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id=?",
                    (rival_pid,),
                ).fetchone()
                rival_name = (rival_name_row[0] if rival_name_row
                              else f"Promo {rival_pid}")
                from services.rival_ai._shared import write_news_item
                write_news_item(
                    conn,
                    headline=f"You won {fighter_name} in a bidding war with {rival_name}",
                    body=(f"{fighter_name} has signed with your promotion "
                          f"after you outbid {rival_name}. The fighter "
                          f"chose your offer — the future is yours to "
                          f"build together."),
                    topic='signing',
                    sentiment='positive',
                    promotion_id=pid,
                    fighter_id=fid,
                    published_at=sim_date,
                )
                conn.commit()
                return {
                    "ok": True,
                    "accepted": True,
                    "chosen_promo_id": pid,
                    "chosen_promo_name": "your promotion",
                    "reason": (f"{fighter_name} chose your offer — "
                               f"he's yours."),
                    "fighter_id": fid,
                    "fighter_name": fighter_name,
                    "player_offer_score": float(player_score),
                    "rival_offer_score": float(rival_score),
                    "contract_id": contract_id,
                    "cost_value": salary,
                    "cost_display": _format_cash(salary),
                    "signing_bonus": signing_bonus,
                    "signing_bonus_display": _format_cash(signing_bonus),
                    "contract_length": contract_length,
                    "win_bonus_pct": win_bonus_pct,
                }
            else:
                # Rival AI wins — sign with the rival promo at the
                # rival's stored salary. The player's counter is logged
                # on the alert for audit, but no contract is created.
                rival_intent = {
                    'fighter_id': fid,
                    'promotion_id': rival_pid,
                    'offer_score': rival_score,
                    'base_salary': rival_salary,
                }
                from services.rival_ai.signing_agent import _try_sign
                _try_sign(conn, rival_intent, rival_salary, sim_date)
                # Update the alert.
                conn.execute(
                    "UPDATE bidding_alerts SET status='won_by_rival', "
                    "player_offer_salary=?, player_offer_bonus=?, "
                    "player_offer_score=?, resolved_date=? "
                    "WHERE alert_id=?",
                    (salary, signing_bonus, player_score,
                     sim_date, alert_id),
                )
                # Write "you lost X" news item.
                rival_name_row = conn.execute(
                    "SELECT name FROM promotions WHERE promotion_id=?",
                    (rival_pid,),
                ).fetchone()
                rival_name = (rival_name_row[0] if rival_name_row
                              else f"Promo {rival_pid}")
                from services.rival_ai._shared import write_news_item
                write_news_item(
                    conn,
                    headline=f"You lost {fighter_name} to {rival_name}",
                    body=(f"{fighter_name} has signed with {rival_name} "
                          f"despite your counter-offer. The fighter chose "
                          f"their offer — better luck next time."),
                    topic='bidding_war_lost',
                    sentiment='negative',
                    promotion_id=pid,
                    fighter_id=fid,
                    published_at=sim_date,
                )
                conn.commit()
                return {
                    "ok": True,
                    "accepted": False,
                    "chosen_promo_id": rival_pid,
                    "chosen_promo_name": rival_name,
                    "reason": (f"{fighter_name} chose {rival_name}'s offer. "
                               f"Your bid wasn't enough."),
                    "fighter_id": fid,
                    "fighter_name": fighter_name,
                    "player_offer_score": float(player_score),
                    "rival_offer_score": float(rival_score),
                }
        except Exception as e:
            print(f"[api.counter_offer] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "accepted": False, "error": str(e),
                    "reason": "An internal error occurred."}

    def _compute_fighter_desirability(self, promo_id, fighter_id, salary,
                                       signing_bonus, conn):
        """Compute the fighter's desirability score (0..1+) for an offer
        from `promo_id` with `salary` + `signing_bonus`.

        Per Phase M3.2 spec — the fighter chooses based on:
          - Promo reputation (higher = more attractive)
          - Salary (higher = better)
          - Signing bonus (higher = better)
          - Promo size_tier fit (major wants stars, grassroots wants
            prospects — the fighter's effective_ceiling + age should
            match the promo's archetype)

        UNIFIED formula — used for BOTH the rival AI's stored offer
        (recomputed at counter_offer time using the rival's stored
        salary) AND the player's counter-offer. This makes the
        comparison fair: the rival AI's internal offer_score (which
        includes path_to_title, budget, etc. — what the PROMO cares
        about) is NOT what the fighter cares about. The fighter cares
        about (reputation, salary, bonus, fit) — captured here.

        We use effective_ceiling = potential * realization so a "bust"
        (potential=85, realization=0.5, ceiling=42) is priced like a
        42-potential fighter (Phase M3.3 fair-value fix). A major
        promo with size_tier fit (ceiling >= 65) gets +0.10 fit bonus.

        Weights:
          0.25 * (reputation / 100)
          0.25 * (log10(salary+1) / 8)        # salary scaled to 0..1
          0.20 * (log10(signing_bonus+1) / 6) # bonus scaled to 0..1
          0.10 * staff_quality                # promo staff count / 8
          0.10 * (1 - age / 40)               # younger = more upside
          0.10 * (effective_ceiling / 100)
          + size_tier_fit (0 or +0.10)
        """
        import math
        promo_row = conn.execute(
            "SELECT reputation, size_tier FROM promotions "
            "WHERE promotion_id=?",
            (promo_id,),
        ).fetchone()
        if not promo_row:
            return 0.0
        rep, size_tier = promo_row
        rep = max(0, min(100, rep or 0)) / 100.0
        # Salary: log10(salary + 1) / 8 — $100K maps to ~0.625, $500K
        # maps to ~0.75. The denominator 8 ensures $1M → ~1.0.
        sal = math.log10(max(0.0, float(salary or 0)) + 1) / 8.0
        sal = max(0.0, min(1.0, sal))
        # Signing bonus: log10(bonus + 1) / 6 — $100K → ~0.83, $1M → ~1.0.
        bon = math.log10(max(0.0, float(signing_bonus or 0)) + 1) / 6.0
        bon = max(0.0, min(1.0, bon))
        # Staff quality: count of non-coach promo staff / 8.
        staff_count_row = conn.execute(
            "SELECT COUNT(*) FROM staff "
            "WHERE promotion_id=? AND role_type != 'coach'",
            (promo_id,),
        ).fetchone()
        staff = min(1.0, (staff_count_row[0] if staff_count_row else 0) / 8.0)
        # Fighter age + effective_ceiling.
        frow = conn.execute(
            "SELECT f.date_of_birth, "
            "       COALESCE(fc.potential, 50) AS potential, "
            "       COALESCE(fc.realization, 0.7) AS realization "
            "FROM fighters f "
            "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
            "WHERE f.fighter_id=?",
            (fighter_id,),
        ).fetchone()
        if not frow:
            return 0.0
        dob, potential, realization = frow
        effective_ceiling = (potential or 50) * (realization or 0.7)
        talent = max(0.0, min(1.0, effective_ceiling / 100.0))
        # Age: compute from date_of_birth + current sim date.
        age = 28
        try:
            cur_row = conn.execute(
                "SELECT current_date FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            if cur_row and cur_row[0] and dob:
                cur_dt = datetime.strptime(cur_row[0], "%Y-%m-%d")
                dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                age = cur_dt.year - dob_dt.year
                if (cur_dt.month, cur_dt.day) < (dob_dt.month, dob_dt.day):
                    age -= 1
        except (ValueError, TypeError):
            pass
        youth = max(0.0, 1.0 - age / 40.0)
        # Size-tier fit: major promo wants stars (ceiling >= 65),
        # grassroots wants prospects (age <= 25 + ceiling <= 75), mid
        # wants developing (age <= 28 + ceiling >= 50). A fighter who
        # matches the promo's archetype gets +0.10 fit bonus.
        fit = 0.0
        if size_tier == 'major' and effective_ceiling >= 65:
            fit = 0.10
        elif size_tier == 'small' and age <= 25 and effective_ceiling <= 75:
            fit = 0.10  # grassroots wants young prospects
        elif size_tier == 'mid' and age <= 28 and effective_ceiling >= 50:
            fit = 0.10
        base = (0.25 * rep + 0.25 * sal + 0.20 * bon + 0.10 * staff
                + 0.10 * youth + 0.10 * talent + fit)
        return max(0.0, min(1.0, base))

    def _compute_player_offer_score(self, player_pid, fighter_id,
                                     salary, signing_bonus, conn):
        """Backward-compat alias for _compute_fighter_desirability.

        Kept so any external callers that referenced the old name
        still work. Internally delegates to _compute_fighter_desirability
        (the unified formula used for BOTH player and rival offers).
        """
        return self._compute_fighter_desirability(
            player_pid, fighter_id, salary, signing_bonus, conn,
        )

    def cut_fighter(self, fighter_id):
        """Release a fighter from the player's promotion.

        Per NAV_BUTTONS_AUDIT §2.4 + §3.2:
          - Verifies the fighter is on the player's roster.
          - Sets current_promotion_id = NULL.
          - Marks the active contract status='terminated'.
          - Generates a news item: "<fighter> released by <promo>".
          - Returns {ok, fighter_id, news_headline}.

        Does NOT publish an event (the FIGHTER_CUT event type doesn't
        exist yet — a future task will add it). The contract is
        terminated inline.
        """
        try:
            fid = int(fighter_id)
            conn = self.conn
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}

            # Verify ownership
            row = conn.execute(
                "SELECT current_promotion_id, is_active, first_name, last_name "
                "FROM fighters WHERE fighter_id=?",
                (fid,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": f"Fighter {fid} not found."}
            if row[0] != pid:
                return {"ok": False, "error": "Fighter is not on your roster."}

            fighter_name = f"{row[2]} {row[3]}"
            promo_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?", (pid,)
            ).fetchone()
            promo_name = promo_row[0] if promo_row else f"Promotion {pid}"

            # 1. Update fighter
            conn.execute(
                "UPDATE fighters SET current_promotion_id = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE fighter_id=?",
                (fid,),
            )

            # 2. Terminate active contracts
            conn.execute(
                "UPDATE contracts SET status='terminated', "
                "updated_at = CURRENT_TIMESTAMP "
                "WHERE contract_id IN ("
                "  SELECT fc.contract_id FROM fighter_contracts fc "
                "  WHERE fc.fighter_id=?"
                ") AND status='active'",
                (fid,),
            )

            # 3. Vacate any titles held
            conn.execute(
                "UPDATE titles SET current_champion_fighter_id = NULL, "
                "is_vacant = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE current_champion_fighter_id=?",
                (fid,),
            )

            # 4. News item
            # NEWS-SPAM-MEMORY-CHECK — release news is MAJOR (roster
            # move the player cares about). Was defaulting to ROUTINE
            # via direct INSERT (the topic was 'signing' but no
            # importance was set, so it fell to the column default).
            src_row = conn.execute(
                "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
            ).fetchone()
            src_id = src_row[0] if src_row else None
            if src_id:
                conn.execute(
                    "INSERT INTO news_items (news_source_id, headline, body, "
                    "sentiment, topic, fighter_id, promotion_id, published_at, importance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (src_id,
                     f"{fighter_name} released by {promo_name}",
                     f"{fighter_name} has been released from {promo_name}. "
                     "The roster move frees up cap space and opens the door "
                     "for new signings.",
                     "negative", "release", fid, pid,
                     get_clock(conn)[0] if get_clock(conn) else None,
                     "MAJOR"),
                )

            # PHASE-R (Reward Layer §6 Principle 4): log the cut
            # decision so it can echo later (e.g. "Since you cut him
            # in May, he's won 2 of 3 for [Rival Promo]").
            try:
                from player_decisions import log_decision, TYPE_CUT
                cut_date = get_clock(conn)[0] if get_clock(conn) else None
                log_decision(
                    conn, TYPE_CUT,
                    target_fighter_id=fid,
                    target_promo_id=pid,
                    context={
                        "promo_name": promo_name,
                        "fighter_name": fighter_name,
                    },
                    decision_date=cut_date,
                )
            except Exception as e:
                print(f"[app_web.cut_fighter] WARN: log_decision "
                      f"failed: {e}", flush=True)

            conn.commit()
            return {
                "ok": True,
                "fighter_id": fid,
                "news_headline": f"{fighter_name} released by {promo_name}",
            }
        except Exception as e:
            print(f"[api.cut_fighter] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # STAFF MARKET — Phase E4 (docs/ECON_STAFF_PLAN.md §4 + §5.3)
    # ============================================================

    def get_staff_market_data(self, page=1, filters=None):
        """Return paginated free-agent staff for the Staff Market screen.

        Per docs/ECON_STAFF_PLAN.md §4.3.1 + §5.3 + task brief:
          - Lists all `staff` rows where promotion_id IS NULL AND
            gym_id IS NULL (truly free — not promo-bound, not gym-
            resident). This is the post-v3.22.0-migration free-agent
            pool (~200 coaches initially).
          - Filterable by role_type + skill_phrase + search (200ms
            debounce on the JS side).
          - Paginated 20/page (matches Free Agents).
          - Each staff row: staff_id, name, age, role_type, role_label,
            skill_phrase ('world-class'/'established'/'promising'/
            'unproven' — NEVER the raw 0-100 int), salary_ask,
            salary_ask_display, contract_length_ask, specialty_summary.

        Args:
          page: int (1-based, default 1)
          filters: optional dict {role_type, skill, search}

        Returns:
          {
            staff: [...],       # 20 rows max
            total: int,         # total free-agent count (across all pages)
            page: int,
            per_page: int,      # 20
            total_pages: int,
            role_counts: {role_type: count, ...}  # for filter dropdown
          }
        """
        try:
            page = max(1, int(page or 1))
            filters = filters or {}
            per_page = 20
            conn = self.conn

            # --- Build WHERE clause from filters ---
            # CR-DESIGN: coaches are NOT hireable by promos. They belong
            # to the gym ecosystem (fighters choose gyms, promos don't
            # hire coaches). Exclude them from the Staff Market entirely.
            where_clauses = [
                "s.promotion_id IS NULL",
                "s.gym_id IS NULL",
                "s.role_type != 'coach'",
            ]
            params = []
            role_filter = (filters.get("role_type") or "").strip()
            if role_filter and role_filter != "all":
                where_clauses.append("s.role_type = ?")
                params.append(role_filter)

            # Skill filter — voice phrase → skill_level range.
            # Mirrors _skill_phrase's bands.
            skill_filter = (filters.get("skill") or "").strip()
            if skill_filter and skill_filter != "all":
                skill_bands = {
                    "world-class": (80, 100),
                    "established": (60, 79),
                    "promising": (40, 59),
                    "unproven": (0, 39),
                }
                band = skill_bands.get(skill_filter)
                if band:
                    where_clauses.append(
                        "s.skill_level BETWEEN ? AND ?"
                    )
                    params.extend([band[0], band[1]])

            search = (filters.get("search") or "").strip()
            if search:
                where_clauses.append(
                    "(s.first_name LIKE ? OR s.last_name LIKE ? "
                    "OR (s.first_name || ' ' || s.last_name) LIKE ?)"
                )
                like = f"%{search}%"
                params.extend([like, like, like])

            where_sql = " AND ".join(where_clauses)

            # --- Total count (for pagination) ---
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM staff s WHERE {where_sql}",
                params,
            ).fetchone()
            total = int(total_row[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page

            # --- Page rows ---
            # Sort: world-class first, then established, promising,
            # unproven. Within a tier, by salary_ask DESC (most
            # expensive first — the "stars" of the market).
            rows = conn.execute(
                f"SELECT s.staff_id, s.first_name, s.last_name, s.age, "
                f"      s.role_type, s.skill_level, s.salary_ask, "
                f"      s.contract_length_ask, s.specialty, "
                f"      n.name "
                f"FROM staff s "
                f"LEFT JOIN nations n ON n.nation_id = s.nation_id "
                f"WHERE {where_sql} "
                f"ORDER BY s.skill_level DESC, s.salary_ask DESC, "
                f"         s.last_name "
                f"LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            staff_list = []
            for r in rows:
                (staff_id, fn, ln, age, role_type, skill_level,
                 salary_ask, contract_length_ask, specialty_json,
                 nation_name) = r
                # Parse specialty JSON for a short summary string.
                # For scouts, show their eye_for_talent / bias_style.
                # For coaches, the specialty is a string like
                # 'head_coach:bjj' — show that as-is.
                # For others (GM/doctor/cutman/commentator), specialty
                # is null or a free-text note — show "—".
                specialty_summary = "—"
                if specialty_json:
                    if specialty_json.startswith("{"):
                        try:
                            spec = json.loads(specialty_json)
                            parts = []
                            if "bias_style" in spec:
                                parts.append(str(spec["bias_style"]))
                            if "eye_for_talent" in spec:
                                # Voice phrase, not raw int.
                                parts.append(
                                    _skill_phrase(spec["eye_for_talent"])
                                    + " eye"
                                )
                            specialty_summary = " · ".join(parts) if parts else "—"
                        except Exception:
                            specialty_summary = "—"
                    else:
                        # String specialty (e.g., 'head_coach:bjj').
                        specialty_summary = specialty_json

                staff_list.append({
                    "staff_id": staff_id,
                    "name": f"{fn} {ln}".strip(),
                    "first_name": fn,
                    "last_name": ln,
                    "age": age,
                    "role_type": role_type,
                    "role_label": _role_label(role_type),
                    # Phase 7 / Task A6 — raw skill_level (0-100) int
                    # DROPPED from the JSON payload (per §17.4 "Rich
                    # Not Thin"). The UI shows `skill_phrase` ONLY
                    # ("world-class" / "established" / "promising" /
                    # "unproven"). The SQL ORDER BY still uses
                    # `s.skill_level DESC` internally (server-side sort
                    # key — never crosses the API boundary).
                    "skill_phrase": _skill_phrase(skill_level),
                    "salary_ask": float(salary_ask or 0),
                    "salary_ask_display": _format_cash(
                        float(salary_ask or 0)) + "/yr",
                    "contract_length_ask": int(contract_length_ask or 2),
                    "specialty_summary": specialty_summary,
                    "nation_name": nation_name or "International",
                    "nation_flag": _nation_flag_emoji(nation_name),
                })

            # --- Role counts (for the filter dropdown) ---
            # CR-DESIGN: exclude coaches (gym-bound, not promo staff).
            role_count_rows = conn.execute(
                "SELECT s.role_type, COUNT(*) "
                "FROM staff s "
                "WHERE s.promotion_id IS NULL AND s.gym_id IS NULL "
                "AND s.role_type != 'coach' "
                "GROUP BY s.role_type "
                "ORDER BY 2 DESC"
            ).fetchall()
            role_counts = [
                {"role_type": r[0], "role_label": _role_label(r[0]),
                 "count": int(r[1])}
                for r in role_count_rows
            ]

            return {
                "staff": staff_list,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "role_counts": role_counts,
            }
        except Exception as e:
            print(f"[api.get_staff_market_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"staff": [], "total": 0, "page": 1, "per_page": 20,
                    "total_pages": 1, "role_counts": [],
                    "error": str(e)}

    # ============================================================
    # P1-WIRE-4-SCREENS — Scouting screen
    # ============================================================
    # Per docs/P1_PLAN_WIRE_SCREENS.md §3 + docs/REVIEW_P1_SCREEN_BACKENDS.md
    # §1: returns player's signed scouts + recent reports + an
    # assign_scout() action that wraps scouting.assign_scout (752 LOC).
    # The backend is fully coded — the player just hasn't had a UI to
    # drive assignments yet (0 reports in DB).
    # ------------------------------------------------------------

    def get_scouting_data(self):
        """Return the player's scouts + recent reports for the Scouting screen.

        Returns:
          {
            "player_scouts": [
              {
                "staff_id", "name", "skill_phrase", "salary_display",
                "eye_for_talent_phrase", "tech_phrase", "character_phrase",
                "mistake_phrase", "bias_style", "bias_nationality",
                "bias_aggression",
                "current_assignment": null | {
                  "fighter_id", "fighter_name", "fighter_nickname",
                  "start_date", "eta_date", "days_remaining"
                }
              }, ...
            ],
            "recent_reports": [
              {
                "scouting_report_id", "target_fighter_id",
                "target_name", "target_nickname",
                "scout_name", "report_date", "report_date_display",
                "estimated_potential", "estimated_ceiling",
                "estimated_floor",
                "estimated_strengths": [...],  # parsed JSON
                "estimated_weaknesses": [...],
                "marketability_assessment",
                "injury_risk_assessment",
                "contract_cost_estimate",
                "contract_cost_display",
                "confidence_phrase",
                "is_stale", "report_text"
              }, ...
            ],
            "free_agent_scouts_count": int,
            "player_promo_id": int
          }

        Voice compliance (CONVENTIONS §14 + §17.4 "Rich Not Thin"):
          - All estimated_* fields are voice descriptors (already
            in the DB per scouting.generate_scouting_report).
          - Phase 7 / Task A5: the raw `scout_confidence` (0-100)
            int has been DROPPED from the JSON payload. The UI
            shows `confidence_phrase` ONLY ("HIGHLY CONFIDENT" /
            "MODERATELY CONFIDENT" / "UNCERTAIN" / "WILD GUESS").
            The previous "scout's own rating, NOT a fighter
            attribute" carve-out was a §14 violation — a raw 0-100
            int shown as text violates §17.4 regardless of
            semantics. Same drop in `get_scouting_report()`.
          - contract_cost_estimate is a dollar value (carve-out OK).
          - eye_for_talent / technical_analysis / character_reading
            are scout attributes (0-100 ints) — wrapped in voice
            phrases, NEVER shown raw.
          - mistake_rate is shown as a reliability phrase
            ('sharp' / 'reliable' / 'occasional miss' / 'wild card').
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False,
                        "error": "No player promotion selected."}
            conn = self.conn

            # Current sim date for ETA computation.
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            try:
                sim_dt = datetime.strptime(sim_date_str, "%Y-%m-%d") \
                    if sim_date_str else None
            except (ValueError, TypeError):
                sim_dt = None

            # ---- Player's signed scouts ----
            scout_rows = conn.execute(
                "SELECT s.staff_id, s.first_name, s.last_name, "
                "  s.skill_level, s.salary_ask, s.specialty "
                "FROM staff s "
                "WHERE s.role_type='scout' AND s.promotion_id=? "
                "ORDER BY s.skill_level DESC, s.last_name",
                (pid,)
            ).fetchall()

            player_scouts = []
            for r in scout_rows:
                (sid, fn, ln, skill_level, salary, specialty_json) = r
                attrs = {}
                if specialty_json:
                    try:
                        attrs = json.loads(specialty_json)
                    except Exception:
                        attrs = {}
                # Parse current assignment + compute ETA.
                assignment = None
                ca = attrs.get("current_assignment")
                if ca:
                    start_str = attrs.get("assignment_start_date")
                    a_row = conn.execute(
                        "SELECT first_name, last_name, nickname "
                        "FROM fighters WHERE fighter_id=?",
                        (ca,)
                    ).fetchone()
                    a_name = "Unknown"
                    a_nick = ""
                    if a_row:
                        a_name = f"{a_row[0] or ''} {a_row[1] or ''}".strip()
                        a_nick = a_row[2] or ""
                    eta_date = None
                    days_remaining = None
                    if start_str:
                        try:
                            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
                            from scouting import SCOUTING_DURATION_DAYS
                            eta_dt = start_dt + timedelta(days=SCOUTING_DURATION_DAYS)
                            eta_date = eta_dt.strftime("%Y-%m-%d")
                            if sim_dt:
                                days_remaining = (eta_dt - sim_dt).days
                        except (ValueError, TypeError):
                            pass
                    assignment = {
                        "fighter_id": ca,
                        "fighter_name": a_name,
                        "fighter_nickname": a_nick,
                        "start_date": start_str or "",
                        "eta_date": eta_date or "",
                        "days_remaining": days_remaining,
                    }
                player_scouts.append({
                    "staff_id": sid,
                    "name": f"{fn or ''} {ln or ''}".strip(),
                    "skill_phrase": _skill_phrase(skill_level),
                    "salary_display": _format_cash(float(salary or 0)) + "/yr",
                    "eye_for_talent_phrase": _scout_attr_phrase(
                        attrs.get("eye_for_talent"), "eye"),
                    "tech_phrase": _scout_attr_phrase(
                        attrs.get("technical_analysis"), "tech"),
                    "character_phrase": _scout_attr_phrase(
                        attrs.get("character_reading"), "character"),
                    "mistake_phrase": _scout_reliability_phrase(
                        attrs.get("mistake_rate")),
                    "bias_style": attrs.get("bias_style") or "",
                    "bias_nationality": attrs.get("bias_nationality") or "",
                    "bias_aggression": attrs.get("bias_aggression"),
                    "current_assignment": assignment,
                })

            # ---- Recent scouting reports (across all scouts — limit 20) ----
            report_rows = conn.execute(
                "SELECT sr.scouting_report_id, sr.target_fighter_id, "
                "  sr.scout_id, sr.report_date, "
                "  sr.estimated_potential, sr.estimated_ceiling, "
                "  sr.estimated_floor, sr.estimated_strengths, "
                "  sr.estimated_weaknesses, sr.marketability_assessment, "
                "  sr.injury_risk_assessment, sr.contract_cost_estimate, "
                "  sr.scout_confidence, sr.is_stale, sr.report_text, "
                "  f.first_name, f.last_name, f.nickname, "
                "  st.first_name, st.last_name "
                "FROM scouting_reports sr "
                "LEFT JOIN fighters f ON f.fighter_id=sr.target_fighter_id "
                "LEFT JOIN staff st ON st.staff_id=sr.scout_id "
                "ORDER BY sr.report_date DESC, sr.scouting_report_id DESC "
                "LIMIT 20"
            ).fetchall()

            recent_reports = []
            for r in report_rows:
                (rid, target_id, scout_id, report_date,
                 pot, ceil, floor, str_json, weak_json,
                 market, injury, contract_cost, confidence,
                 is_stale, report_text,
                 tfn, tln, tnick, sfn, sln) = r
                # Parse JSON arrays for strengths/weaknesses.
                def _parse_json_list(s):
                    if not s:
                        return []
                    try:
                        v = json.loads(s)
                        if isinstance(v, list):
                            return [str(x) for x in v if x]
                        return [str(v)]
                    except Exception:
                        return []
                strengths = _parse_json_list(str_json)
                weaknesses = _parse_json_list(weak_json)
                target_name = f"{tfn or ''} {tln or ''}".strip() or "Unknown"
                scout_name = f"{sfn or ''} {sln or ''}".strip() or "Unknown Scout"
                recent_reports.append({
                    "scouting_report_id": rid,
                    "target_fighter_id": target_id,
                    "target_name": target_name,
                    "target_nickname": tnick or "",
                    "scout_id": scout_id,
                    "scout_name": scout_name,
                    "report_date": report_date or "",
                    "report_date_display": _format_long_date(report_date),
                    "estimated_potential": pot or "",
                    "estimated_ceiling": ceil or "",
                    "estimated_floor": floor or "",
                    "estimated_strengths": strengths,
                    "estimated_weaknesses": weaknesses,
                    "marketability_assessment": market or "",
                    "injury_risk_assessment": injury or "",
                    "contract_cost_estimate": contract_cost,
                    "contract_cost_display": _format_cash(
                        float(contract_cost or 0)) if contract_cost else "—",
                    # Phase 7 / Task A5 — raw scout_confidence (0-100
                    # int) DROPPED from the JSON payload (per §17.4
                    # "Rich Not Thin"). The UI shows `confidence_phrase`
                    # ONLY ("HIGHLY CONFIDENT" / "UNCERTAIN" / etc.).
                    "confidence_phrase": _scout_confidence_phrase(
                        int(confidence or 0)),
                    "is_stale": bool(is_stale),
                    "report_text": report_text or "",
                })

            # ---- Free-agent scout count (CTA to Staff Market) ----
            fa_count = conn.execute(
                "SELECT COUNT(*) FROM staff "
                "WHERE role_type='scout' AND promotion_id IS NULL "
                "AND gym_id IS NULL"
            ).fetchone()[0]

            return {
                "player_scouts": player_scouts,
                "recent_reports": recent_reports,
                "free_agent_scouts_count": int(fa_count or 0),
                "player_promo_id": pid,
            }
        except Exception as e:
            print(f"[api.get_scouting_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e),
                    "player_scouts": [], "recent_reports": [],
                    "free_agent_scouts_count": 0}

    def assign_scout(self, scout_id, target_fighter_id):
        """Assign a scout to evaluate a target fighter.

        Wraps scouting.assign_scout (752 LOC) — stores the assignment
        in the scout's specialty JSON; the report will be generated
        after SCOUTING_DURATION_DAYS (7) sim days by
        _check_scouting_assignments on each tick.

        Returns:
          {
            "ok": bool,
            "scout_id": int,
            "target_fighter_id": int,
            "eta_date": str|None,        # YYYY-MM-DD
            "days_remaining": int|None,
            "error": str (if !ok)
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False,
                        "error": "No player promotion selected."}
            sid = int(scout_id or 0)
            fid = int(target_fighter_id or 0)
            if not sid or not fid:
                return {"ok": False, "error": "Missing scout_id or fighter_id."}
            conn = self.conn
            # Verify the scout belongs to the player's promo.
            scout_row = conn.execute(
                "SELECT promotion_id FROM staff "
                "WHERE staff_id=? AND role_type='scout'",
                (sid,)
            ).fetchone()
            if not scout_row:
                return {"ok": False,
                        "error": "Scout not found."}
            if int(scout_row[0] or 0) != int(pid):
                return {"ok": False,
                        "error": "Scout is not on your staff."}
            # Verify the target fighter exists + isn't on player's roster
            # (you can only scout fighters you don't own — per the
            # get_fighter_profile_data embed pattern).
            fighter_row = conn.execute(
                "SELECT current_promotion_id, is_active, is_retired "
                "FROM fighters WHERE fighter_id=?",
                (fid,)
            ).fetchone()
            if not fighter_row:
                return {"ok": False,
                        "error": "Target fighter not found."}
            f_promo, f_active, f_retired = fighter_row
            if int(f_promo or 0) == int(pid):
                return {"ok": False,
                        "error": "You can't scout a fighter on your own roster."}
            if not f_active or f_retired:
                return {"ok": False,
                        "error": "That fighter isn't an active scouted target."}

            # Delegate to scouting.assign_scout.
            import scouting
            ok = scouting.assign_scout(
                conn, sid, fid, promotion_id=pid)
            if not ok:
                return {"ok": False,
                        "error": "Scout is already on assignment. Cancel "
                                 "the current one first."}
            # HW3.4 — log a 'scout' decision so the echoes engine
            # can surface "X, who you scouted in [Month], has since
            # improved/regressed — your scout was right/wrong." on
            # future Advance Days. Per docs/Hardening_Phase.md §HW3.4
            # (echoes quality audit found that scouting_echo never
            # fired because no 'scout' decisions were being logged).
            try:
                from player_decisions import log_decision, TYPE_SCOUT
                log_decision(
                    conn, TYPE_SCOUT,
                    target_fighter_id=fid,
                    target_staff_id=sid,
                    target_promo_id=pid,
                    context={"scout_id": sid, "backfilled": False},
                )
            except Exception as e:
                print(f"[app_web.assign_scout] WARN: log_decision "
                      f"failed: {e}", flush=True)
            conn.commit()

            # Compute ETA for the UI.
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            eta_date = None
            days_remaining = None
            try:
                sim_dt = datetime.strptime(sim_date_str, "%Y-%m-%d") \
                    if sim_date_str else None
                from scouting import SCOUTING_DURATION_DAYS
                if sim_dt:
                    eta_dt = sim_dt + timedelta(days=SCOUTING_DURATION_DAYS)
                    eta_date = eta_dt.strftime("%Y-%m-%d")
                    days_remaining = SCOUTING_DURATION_DAYS
            except (ValueError, TypeError):
                pass

            return {
                "ok": True,
                "scout_id": sid,
                "target_fighter_id": fid,
                "eta_date": eta_date,
                "days_remaining": days_remaining,
            }
        except Exception as e:
            print(f"[api.assign_scout] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def cancel_scout_assignment(self, scout_id):
        """Clear a scout's current assignment mid-observation.

        Lets the player reassign a scout without waiting for the 7-day
        observation to complete. The in-progress report is lost (no
        scouting_reports row is written).
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False,
                        "error": "No player promotion selected."}
            sid = int(scout_id or 0)
            if not sid:
                return {"ok": False, "error": "Missing scout_id."}
            conn = self.conn
            # Verify ownership.
            scout_row = conn.execute(
                "SELECT promotion_id, specialty FROM staff "
                "WHERE staff_id=? AND role_type='scout'",
                (sid,)
            ).fetchone()
            if not scout_row:
                return {"ok": False, "error": "Scout not found."}
            if int(scout_row[0] or 0) != int(pid):
                return {"ok": False,
                        "error": "Scout is not on your staff."}
            attrs = {}
            if scout_row[1]:
                try:
                    attrs = json.loads(scout_row[1])
                except Exception:
                    attrs = {}
            if not attrs.get("current_assignment"):
                return {"ok": False,
                        "error": "Scout has no active assignment."}
            attrs["current_assignment"] = None
            attrs["assignment_start_date"] = None
            attrs["assignment_promotion_id"] = None
            import scouting
            scouting._save_scout_attrs(conn, sid, attrs)
            conn.commit()
            return {"ok": True, "scout_id": sid}
        except Exception as e:
            print(f"[api.cancel_scout_assignment] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_scouting_report(self, report_id):
        """Return full detail for a single scouting report.

        Used by the Reports tab's expand-to-full-report modal.
        Returns the same field set as recent_reports items in
        get_scouting_data, plus the multi-line report_text rendered
        as a single string for the modal's prose block.
        """
        try:
            rid = int(report_id or 0)
            if not rid:
                return {"ok": False, "error": "Missing report_id."}
            conn = self.conn
            r = conn.execute(
                "SELECT sr.scouting_report_id, sr.target_fighter_id, "
                "  sr.scout_id, sr.report_date, "
                "  sr.estimated_potential, sr.estimated_ceiling, "
                "  sr.estimated_floor, sr.estimated_strengths, "
                "  sr.estimated_weaknesses, sr.marketability_assessment, "
                "  sr.injury_risk_assessment, sr.contract_cost_estimate, "
                "  sr.scout_confidence, sr.is_stale, sr.report_text, "
                "  f.first_name, f.last_name, f.nickname, "
                "  st.first_name, st.last_name "
                "FROM scouting_reports sr "
                "LEFT JOIN fighters f ON f.fighter_id=sr.target_fighter_id "
                "LEFT JOIN staff st ON st.staff_id=sr.scout_id "
                "WHERE sr.scouting_report_id=?",
                (rid,)
            ).fetchone()
            if not r:
                return {"ok": False, "error": "Report not found."}
            (rid2, target_id, scout_id, report_date,
             pot, ceil, floor, str_json, weak_json,
             market, injury, contract_cost, confidence,
             is_stale, report_text,
             tfn, tln, tnick, sfn, sln) = r
            def _parse_json_list(s):
                if not s:
                    return []
                try:
                    v = json.loads(s)
                    if isinstance(v, list):
                        return [str(x) for x in v if x]
                    return [str(v)]
                except Exception:
                    return []
            return {
                "ok": True,
                "scouting_report_id": rid2,
                "target_fighter_id": target_id,
                "target_name": f"{tfn or ''} {tln or ''}".strip(),
                "target_nickname": tnick or "",
                "scout_id": scout_id,
                "scout_name": f"{sfn or ''} {sln or ''}".strip(),
                "report_date": report_date or "",
                "report_date_display": _format_long_date(report_date),
                "estimated_potential": pot or "",
                "estimated_ceiling": ceil or "",
                "estimated_floor": floor or "",
                "estimated_strengths": _parse_json_list(str_json),
                "estimated_weaknesses": _parse_json_list(weak_json),
                "marketability_assessment": market or "",
                "injury_risk_assessment": injury or "",
                "contract_cost_estimate": contract_cost,
                "contract_cost_display": _format_cash(
                    float(contract_cost or 0)) if contract_cost else "—",
                # Phase 7 / Task A5 — raw scout_confidence (0-100
                # int) DROPPED from the JSON payload (per §17.4
                # "Rich Not Thin"). The UI shows `confidence_phrase`
                # ONLY. (Mirrors `get_scouting_data` change.)
                "confidence_phrase": _scout_confidence_phrase(
                    int(confidence or 0)),
                "is_stale": bool(is_stale),
                "report_text": report_text or "",
            }
        except Exception as e:
            print(f"[api.get_scouting_report] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def estimate_staff_hire_cost(self, staff_id):
        """Return hire cost estimate for a staff member.

        Per task brief: returns {salary_display, signing_bonus_display,
        total_cost_display}. The signing_bonus is a flat 10% of the
        first-year salary_ask (standard agent fee). The total cost
        is salary_ask × contract_length_ask + signing_bonus.

        NEVER returns the raw skill_level int — only formatted cost
        strings (the JS side uses these for the negotiation modal
        default values).

        Args:
          staff_id: int

        Returns:
          {
            staff_id: int,
            salary_value: float,        # the salary_ask
            salary_display: str,        # "$120K/yr"
            signing_bonus_value: float,
            signing_bonus_display: str,
            total_cost_value: float,
            total_cost_display: str,
            contract_length_ask: int,
          }
        """
        try:
            sid = int(staff_id)
            conn = self.conn
            row = conn.execute(
                "SELECT salary_ask, contract_length_ask, role_type "
                "FROM staff WHERE staff_id=?",
                (sid,),
            ).fetchone()
            if not row:
                return {"error": f"Staff {sid} not found."}
            salary_ask = float(row[0] or 50000)
            contract_length_ask = int(row[1] or 2)
            # Signing bonus = 10% of first-year salary (standard).
            signing_bonus = round(salary_ask * 0.10, -2)  # round to $100
            total_cost = salary_ask * contract_length_ask + signing_bonus
            return {
                "staff_id": sid,
                "salary_value": salary_ask,
                "salary_display": _format_cash(salary_ask) + "/yr",
                "signing_bonus_value": signing_bonus,
                "signing_bonus_display": _format_cash(signing_bonus),
                "total_cost_value": total_cost,
                "total_cost_display": _format_cash(total_cost),
                "contract_length_ask": contract_length_ask,
            }
        except Exception as e:
            print(f"[api.estimate_staff_hire_cost] {e}", flush=True)
            return {"error": str(e)}

    def hire_staff(self, staff_id, salary=None, signing_bonus=0,
                   contract_length=2):
        """Hire a free-agent staff member to the player's promotion.

        Per docs/ECON_STAFF_PLAN.md §4.3.1 + task brief:
          - Verifies the staff is a free agent (promotion_id IS NULL
            AND gym_id IS NULL).
          - Acceptance threshold: salary >= salary_ask × 0.9 (per spec).
          - On accept:
            - Sets staff.promotion_id = player_promotion_id.
            - Creates a contracts row (target_type='staff') with the
              player-set salary + contract_length.
            - Creates a staff_contracts row linking contract → staff.
            - Deducts signing_bonus from promo cash immediately
              (finance_transactions row, type='signing_bonus', negative).
            - Writes a player_decisions log entry (TYPE_HIRE_STAFF)
              so the hire "echoes" later on the Dashboard.
          - Returns {ok, staff_id, contract_id, salary_display,
              signing_bonus_display, contract_length, role_label}.

        Args:
          staff_id: int
          salary: float — player-set (from negotiation slider). If
            None, defaults to salary_ask.
          signing_bonus: float — player-set.
          contract_length: int — player-set (years, 1-5).

        Returns:
          {ok, ...} or {ok: False, error: ...}
        """
        try:
            sid = int(staff_id)
            conn = self.conn
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}

            # Fetch the staff row + verify it's a free agent.
            row = conn.execute(
                "SELECT first_name, last_name, role_type, "
                "      promotion_id, gym_id, salary_ask, "
                "      contract_length_ask, age "
                "FROM staff WHERE staff_id=?",
                (sid,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": f"Staff {sid} not found."}
            (fn, ln, role_type, promo_id, gym_id, salary_ask,
             contract_length_ask, age) = row
            if promo_id is not None or gym_id is not None:
                return {"ok": False,
                        "error": "Staff is not a free agent."}

            # Resolve salary (fallback to salary_ask if not provided).
            if salary is None:
                salary = float(salary_ask or 50000)
            else:
                salary = float(salary)
            salary = max(10_000, min(500_000, salary))
            signing_bonus = float(signing_bonus or 0)
            signing_bonus = max(0, min(1_000_000, signing_bonus))
            contract_length = int(contract_length or contract_length_ask or 2)
            contract_length = max(1, min(5, contract_length))

            # --- Acceptance check (per task brief) ---
            # Staff accepts if salary >= salary_ask × 0.9.
            threshold = float(salary_ask or 0) * 0.9
            if salary < threshold:
                role_label = _role_label(role_type)
                return {
                    "ok": False,
                    "error": (
                        f"{fn} {ln} ({role_label}) isn't interested at "
                        f"{_format_cash(salary)}/yr. His floor is "
                        f"{_format_cash(threshold)}/yr."
                    ),
                    "rejected": True,
                    "salary_ask": float(salary_ask or 0),
                    "threshold": threshold,
                }

            # --- Read the sim clock for contract dates ---
            clock = get_clock(conn)
            start_date = clock[0] if clock else None
            if not start_date:
                return {"ok": False, "error": "No sim clock available."}

            # Compute end_date = start_date + contract_length years.
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                end_year = start_dt.year + contract_length
                try:
                    end_dt = start_dt.replace(year=end_year)
                except ValueError:
                    # Feb 29 in a non-leap target year → Feb 28.
                    end_dt = start_dt.replace(year=end_year, day=28)
                end_date = end_dt.strftime("%Y-%m-%d")
            except Exception as e:
                print(f"[app_web.hire_staff] WARN: end_date calc failed: "
                      f"{e}", flush=True)
                end_date = start_date  # fallback — no end_date.

            # --- Create the contract + staff_contracts rows ---
            # Mirror the pattern in services/contracts.py + the
            # v3.14.0 backfill for staff_contracts.
            contract_id = conn.execute(
                "INSERT INTO contracts (contract_target_type, "
                "promotion_id, start_date, end_date, salary, "
                "exclusive_flag, status) "
                "VALUES ('staff', ?, ?, ?, ?, 1, 'active')",
                (pid, start_date, end_date, salary),
            ).lastrowid
            conn.execute(
                "INSERT INTO staff_contracts (contract_id, staff_id, "
                "contract_role) VALUES (?, ?, ?)",
                (contract_id, sid, role_type),
            )

            # --- Assign the staff to the player's promo ---
            conn.execute(
                "UPDATE staff SET promotion_id=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE staff_id=?",
                (pid, sid),
            )

            # --- Deduct signing_bonus from promo cash (immediate hit) ---
            if signing_bonus > 0:
                conn.execute(
                    "INSERT INTO finance_transactions (promotion_id, "
                    "event_id, fighter_id, transaction_type, amount, "
                    "description, transaction_date) "
                    "VALUES (?, NULL, ?, 'signing_bonus', ?, ?, ?)",
                    (pid, None, -signing_bonus,
                     f"staff signing bonus ({_format_cash(signing_bonus)})",
                     start_date),
                )
                conn.execute(
                    "UPDATE promotions SET current_cash = current_cash + ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE promotion_id = ?",
                    (-signing_bonus, pid),
                )

            # --- Log the decision so it can echo later ---
            try:
                from player_decisions import (
                    log_decision, TYPE_HIRE_STAFF,
                )
                log_decision(
                    conn, TYPE_HIRE_STAFF,
                    target_staff_id=sid,
                    target_promo_id=pid,
                    context={
                        "contract_id": contract_id,
                        "staff_name": f"{fn} {ln}",
                        "role_type": role_type,
                        "role_label": _role_label(role_type),
                        "skill_phrase": _skill_phrase(
                            # Read skill_level via a fresh SELECT (defensive —
                            # the row tuple above doesn't include it).
                            conn.execute(
                                "SELECT skill_level FROM staff "
                                "WHERE staff_id=?", (sid,)
                            ).fetchone()[0]
                        ),
                        "salary_value": salary,
                        "salary_display": _format_cash(salary),
                        "signing_bonus": signing_bonus,
                        "signing_bonus_display": _format_cash(signing_bonus),
                        "contract_length_years": contract_length,
                        "start_date": start_date,
                        "end_date": end_date,
                        "total_value": salary * contract_length
                                       + signing_bonus,
                    },
                    decision_date=start_date,
                )
            except Exception as e:
                print(f"[app_web.hire_staff] WARN: log_decision failed: "
                      f"{e}", flush=True)

            conn.commit()
            return {
                "ok": True,
                "staff_id": sid,
                "contract_id": contract_id,
                "staff_name": f"{fn} {ln}",
                "role_label": _role_label(role_type),
                "salary_value": salary,
                "salary_display": _format_cash(salary) + "/yr",
                "signing_bonus": signing_bonus,
                "signing_bonus_display": _format_cash(signing_bonus),
                "contract_length": contract_length,
                "start_date": start_date,
                "end_date": end_date,
            }
        except Exception as e:
            print(f"[api.hire_staff] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # THE WIRE — news feed (INFO-SCREENS-BATCH-1 §1)
    # ============================================================
    #
    # Per docs/SCREEN_DATA_AUDIT.md §1.2 + §7.1: news_items has
    # 16k+ rows across 24 topics, 3 sentiments, 6 news_sources.
    # The Wire surfaces ALL of them (world news, not just player-
    # promo news) so the player gets Discovery reward: who's hot,
    # who's injured, who signed where.
    #
    # Topic taxonomy: 24 raw DB topics collapse to 13 UI filter
    # chips (the spec names signing/injury/finance/retirement/
    # rivalry/title + "etc."). Filter value 'all' shows everything.

    # UI topic groups: {filter_value: (label, [db_topics])}
    _WIRE_TOPIC_GROUPS = {
        "all":            ("All Topics",  None),  # None = no filter
        "signings":       ("Signings",    ["signing", "release", "bidding_war_lost"]),
        "injuries":       ("Injuries",    ["injury"]),
        "suspensions":    ("Suspensions", ["suspension"]),
        "weigh_ins":      ("Weigh-ins",   ["weight_cut"]),
        "fights":         ("Fight Results", ["fight"]),
        "card_reviews":   ("Card Reviews", ["show_rating", "event_hype"]),
        "title_scene":    ("Title Scene",  ["reputation_marker"]),
        "career":         ("Careers",     ["career_arc", "retirement", "prospect", "reclassified"]),
        "bad_blood":      ("Bad Blood",   ["inter_promo_callout", "cross_promo", "tapping_up_rumor"]),
        "finance":        ("Finance",     ["finance"]),
        "training":       ("Training Camps", ["training"]),
        "staff":          ("Staff",       ["staff"]),
        "legacy":         ("Legacy",      ["legacy", "hall_of_fame"]),
        "milestones":     ("Milestones",  ["small_reward"]),
        "wire":           ("The Wire",    ["news_engine"]),
    }

    @classmethod
    def _wire_topic_filter_options(cls):
        """Return the ordered list of (value, label) for the dropdown."""
        opts = []
        for key in [
            "all", "signings", "injuries", "suspensions", "weigh_ins",
            "fights", "card_reviews", "title_scene", "career",
            "bad_blood", "finance", "training", "staff", "legacy",
            "milestones", "wire",
        ]:
            entry = cls._WIRE_TOPIC_GROUPS.get(key)
            if entry:
                opts.append({"value": key, "label": entry[0]})
        return opts

    def get_wire_data(self, page=1, filters=None):
        """Return paginated news items for The Wire screen.

        Args:
          page:    int page number, 1-indexed (20 items per page)
          filters: {
            "topic": "all"|"signings"|...|None  (UI group, see _WIRE_TOPIC_GROUPS)
            "search": str                        (substring match on headline+body)
            "sentiment": "all"|"positive"|"neutral"|"negative"|None
          }

        Returns:
          {
            "items": [
              {"news_item_id", "headline", "body", "body_excerpt",
               "topic", "topic_group_label", "sentiment",
               "fighter_id", "fighter_name", "promotion_id",
               "promo_name", "event_id", "fight_id",
               "published_at", "published_at_display", "source_name"}
            ],
            "page": int, "per_page": 20, "total": int, "total_pages": int,
            "filters": {"topic", "search", "sentiment"},
            "topic_options": [{value, label}, ...]
          }
        """
        try:
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 20
            offset = (page - 1) * per_page

            topic_key = (filters.get("topic") or "all").lower()
            search = (filters.get("search") or "").strip()
            sentiment = (filters.get("sentiment") or "all").lower()

            # Build WHERE clause dynamically.
            where_parts = []
            params = []

            group_entry = self._WIRE_TOPIC_GROUPS.get(topic_key)
            if group_entry and group_entry[1] is not None:
                topics = group_entry[1]
                placeholders = ",".join("?" * len(topics))
                where_parts.append(f"n.topic IN ({placeholders})")
                params.extend(topics)

            if sentiment in ("positive", "neutral", "negative"):
                where_parts.append("n.sentiment = ?")
                params.append(sentiment)

            if search:
                where_parts.append("(n.headline LIKE ? OR n.body LIKE ?)")
                params.extend(["%" + search + "%", "%" + search + "%"])

            where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

            # Count total.
            count_sql = f"SELECT COUNT(*) FROM news_items n{where_sql}"
            total = int(self.conn.execute(count_sql, params).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)

            # Fetch page.
            rows_sql = (
                "SELECT n.news_item_id, n.headline, n.body, n.sentiment, "
                "n.topic, n.fighter_id, n.promotion_id, n.event_id, "
                "n.fight_id, n.published_at, n.news_source_id, "
                "f.first_name, f.last_name, f.nickname, "
                "p.name "
                "FROM news_items n "
                "LEFT JOIN fighters f ON f.fighter_id = n.fighter_id "
                "LEFT JOIN promotions p ON p.promotion_id = n.promotion_id "
                + where_sql +
                " ORDER BY n.published_at DESC, n.news_item_id DESC "
                "LIMIT ? OFFSET ?"
            )
            row_params = list(params) + [per_page, offset]
            rows = self.conn.execute(rows_sql, row_params).fetchall()

            # Resolve news_source names in one pass (cache by id).
            source_ids = {r[10] for r in rows if r[10]}
            source_names = {}
            if source_ids:
                src_rows = self.conn.execute(
                    "SELECT news_source_id, name FROM news_sources "
                    f"WHERE news_source_id IN ({','.join('?' * len(source_ids))})",
                    tuple(source_ids),
                ).fetchall()
                source_names = {s[0]: s[1] for s in src_rows}

            # Build the response items. The topic_group_label maps the
            # raw DB topic back to the UI filter label (so the chip on
            # each row matches what the player would click to filter).
            # Build a reverse lookup: db_topic → group_label.
            topic_to_label = {}
            for _key, (_label, topics) in self._WIRE_TOPIC_GROUPS.items():
                if topics:
                    for t in topics:
                        topic_to_label.setdefault(t, _label)

            items = []
            for r in rows:
                (nid, headline, body, sent, topic, fid, pid, evid, fight_id,
                 published, src_id, fn, ln, nick, promo_name) = r
                # Fighter display name (with nickname if present).
                fighter_name = None
                if fid and (fn or ln):
                    base = f"{fn or ''} {ln or ''}".strip()
                    if nick:
                        fighter_name = f"{base} '{nick}'"
                    else:
                        fighter_name = base
                # Body excerpt — first 180 chars, no HTML.
                body_text = body or ""
                excerpt = body_text[:180]
                if len(body_text) > 180:
                    # Cut at the last word boundary before 180.
                    cut = excerpt.rfind(" ")
                    if cut > 80:
                        excerpt = excerpt[:cut]
                    excerpt = excerpt + "…"
                items.append({
                    "news_item_id": nid,
                    "headline": headline or "",
                    "body": body_text,
                    "body_excerpt": excerpt,
                    "topic": topic or "wire",
                    "topic_group_label": topic_to_label.get(topic, "The Wire"),
                    "sentiment": sent or "neutral",
                    "fighter_id": fid,
                    "fighter_name": fighter_name,
                    "promotion_id": pid,
                    "promo_name": promo_name or "",
                    "event_id": evid,
                    "fight_id": fight_id,
                    "published_at": published or "",
                    "published_at_display": (published or "")[:10],  # YYYY-MM-DD
                    "source_name": source_names.get(src_id, "") if src_id else "",
                })

            return {
                "items": items,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "filters": {"topic": topic_key, "search": search, "sentiment": sentiment},
                "topic_options": self._wire_topic_filter_options(),
            }
        except Exception as e:
            print(f"[api.get_wire_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e), "items": [], "page": 1,
                    "per_page": 20, "total": 0, "total_pages": 1,
                    "filters": filters or {}, "topic_options": []}

    # ============================================================
    # THE ARCHIVE — past events (INFO-SCREENS-BATCH-1 §2)
    # ============================================================
    #
    # Per docs/SCREEN_DATA_AUDIT.md §1.2: events has 2255 completed
    # rows; promo 1 has 447. The Archive is the player's book of
    # past cards — the Attachment reward ("I remember that card").
    #
    # Two API methods:
    #   1. get_archive_data(page, filters) — paginated list of the
    #      player's completed events with main-event result, venue,
    #      rating voice phrase, net profit (from finance_transactions).
    #   2. get_event_card(event_id) — the full fight list for one
    #      event, called on expand. Returns Red/Blue corners, result,
    #      round, weight class, title-fight flag.
    #
    # Voice compliance (CONVENTIONS §14 + REWARD_REVIEW Principle 5):
    #   - Show ratings as voice phrases ("instant classic" / "solid
    #     night" / "lackluster"), never raw ints.
    #   - Net profit displayed with a voice caption ("in the black" /
    #     "took a bath" / "broke even"), no raw number unless it's
    #     the actual cash figure (which is OK — the player is the
    #     owner of that money).
    #   - Ownership language: section is "YOUR PAST CARDS".

    @staticmethod
    def _archive_rating_phrase(rating):
        """Voice phrase for an event's overall_rating (0-100 int).

        Per spec: 'instant classic' / 'solid night' / 'lackluster'.
        Returns (phrase, tier_label, color) — tier_label is a short
        tag for the chip; color is a CSS var name.
        """
        if rating is None:
            return ("card data lost to time", "UNRATED", "var(--text-tertiary)")
        r = int(rating)
        if r >= 85:
            return ("an instant classic — fans will talk about this for years",
                    "INSTANT CLASSIC", "var(--green)")
        if r >= 75:
            return ("a memorable night of fights",
                    "MEMORABLE", "var(--green)")
        if r >= 65:
            return ("a solid night at the office",
                    "SOLID NIGHT", "var(--gold)")
        if r >= 55:
            return ("a decent show that didn't quite deliver",
                    "DECENT", "var(--warning)")
        if r >= 40:
            return ("a lackluster card the fans won't remember",
                    "LACKLUSTER", "var(--crimson)")
        return ("a night to forget",
                "DISASTER", "var(--crimson)")

    @staticmethod
    def _archive_net_profit_voice(net_profit, current_cash):
        """Voice caption for an event's net profit.

        Returns a short phrase like 'in the black' / 'took a bath' /
        'broke even' / 'ledger sealed' (when no finance data).
        """
        if net_profit is None:
            return "ledger sealed"
        np = float(net_profit)
        if np > 1_000_000:
            return "a windfall night"
        if np > 100_000:
            return "in the black"
        if np > 0:
            return "scraped a profit"
        if np == 0:
            return "broke even"
        if np > -100_000:
            return "took a small loss"
        if np > -1_000_000:
            return "took a bath"
        return "a financial disaster"

    def get_archive_data(self, page=1, filters=None):
        """Return paginated past events for the player's promotion.

        Args:
          page:    int page number (10 events per page)
          filters: {
            "date_from": "YYYY-MM-DD"|None   (inclusive lower bound)
            "date_to":   "YYYY-MM-DD"|None   (inclusive upper bound)
            "search":    str                 (substring match on event_name)
            "min_rating": int|None           (only events with overall_rating >= N)
          }

        Returns:
          {
            "events": [
              {
                "event_id", "event_name", "event_date", "event_date_display",
                "venue_name", "venue_capacity", "city_name",
                "overall_rating", "rating_phrase", "rating_tier_label",
                "rating_tier_color",
                "main_event": {
                  "fight_id", "winner_id", "winner_name", "winner_nickname",
                  "loser_id", "loser_name", "loser_nickname",
                  "result_type", "result_label", "finish_round", "finish_time",
                  "is_title_fight", "weight_class_name"
                } | null,
                "revenue", "expenses", "net_profit", "net_profit_display",
                "net_profit_voice",
                "n_fights", "n_title_fights"
              }
            ],
            "page", "per_page": 10, "total", "total_pages", "filters",
            "promo_id", "promo_name"
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 10
            offset = (page - 1) * per_page

            date_from = (filters.get("date_from") or "").strip() or None
            date_to = (filters.get("date_to") or "").strip() or None
            search = (filters.get("search") or "").strip()
            try:
                min_rating = int(filters.get("min_rating")) if filters.get("min_rating") else None
            except (TypeError, ValueError):
                min_rating = None

            where_parts = ["e.promotion_id = ?", "e.status = 'completed'"]
            params = [pid]
            if date_from:
                where_parts.append("e.event_date >= ?")
                params.append(date_from)
            if date_to:
                where_parts.append("e.event_date <= ?")
                params.append(date_to)
            if search:
                where_parts.append("e.event_name LIKE ?")
                params.append("%" + search + "%")
            if min_rating is not None:
                where_parts.append("sr.overall_rating >= ?")
                params.append(min_rating)
            where_sql = " WHERE " + " AND ".join(where_parts)

            # Promo name.
            p_row = self.conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?", (pid,)).fetchone()
            promo_name = p_row[0] if p_row else "Your Promotion"

            # Count total.
            count_sql = (
                "SELECT COUNT(*) FROM events e "
                "LEFT JOIN show_ratings sr ON sr.event_id=e.event_id "
                + where_sql
            )
            total = int(self.conn.execute(count_sql, params).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)

            # Fetch the page (need venue + city + show_rating).
            rows_sql = (
                "SELECT e.event_id, e.event_name, e.event_date, "
                "v.name, v.capacity, c.name, "
                "sr.overall_rating, sr.rating_description "
                "FROM events e "
                "LEFT JOIN venues v ON v.venue_id = e.venue_id "
                "LEFT JOIN cities c ON c.city_id = v.city_id "
                "LEFT JOIN show_ratings sr ON sr.event_id = e.event_id "
                + where_sql +
                " ORDER BY e.event_date DESC, e.event_id DESC "
                "LIMIT ? OFFSET ?"
            )
            row_params = list(params) + [per_page, offset]
            rows = self.conn.execute(rows_sql, row_params).fetchall()

            # For each event, fetch the main event + finance summary +
            # fight counts in one batched pass per event (cheap; we
            # only fetch 10 events per page so 30 extra small queries).
            events = []
            for r in rows:
                (eid, ename, edate, vname, vcap, cname, rating, rating_desc) = r
                # Main event: prefer card_slot='main_event'; fall back
                # to the first fight on the card if no slot is set.
                me_row = self.conn.execute(
                    "SELECT f.fight_id, f.winner_fighter_id, f.loser_fighter_id, "
                    "f.result_type, f.finish_round, f.finish_time, "
                    "f.is_title_fight, f.weight_class_id, "
                    "wf.first_name, wf.last_name, wf.nickname, "
                    "lf.first_name, lf.last_name, lf.nickname, "
                    "wc.name "
                    "FROM fights f "
                    "LEFT JOIN fighters wf ON wf.fighter_id=f.winner_fighter_id "
                    "LEFT JOIN fighters lf ON lf.fighter_id=f.loser_fighter_id "
                    "LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
                    "WHERE f.event_id=? "
                    "ORDER BY CASE f.card_slot "
                    "  WHEN 'main_event' THEN 1 WHEN 'co_main' THEN 2 "
                    "  WHEN 'featured_prelim' THEN 3 WHEN 'prelim' THEN 4 "
                    "  ELSE 5 END, f.fight_id ASC LIMIT 1",
                    (eid,),
                ).fetchone()
                main_event = None
                if me_row:
                    (fid, wid, lid, rtype, frnd, ftime, is_title, wc_id,
                     wfn, wln, wnick, lfn, lln, lnick, wc_name) = me_row
                    main_event = {
                        "fight_id": fid,
                        "winner_id": wid,
                        "winner_name": f"{wfn or ''} {wln or ''}".strip() if (wfn or wln) else "—",
                        "winner_nickname": wnick or "",
                        "loser_id": lid,
                        "loser_name": f"{lfn or ''} {lln or ''}".strip() if (lfn or lln) else "—",
                        "loser_nickname": lnick or "",
                        "result_type": rtype or "",
                        "result_label": _result_type_label(rtype),
                        "finish_round": frnd,
                        "finish_time": ftime or "",
                        "is_title_fight": bool(is_title),
                        "weight_class_name": wc_name or "",
                    }

                # Fight counts.
                cnt_row = self.conn.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN is_title_fight=1 THEN 1 ELSE 0 END) "
                    "FROM fights WHERE event_id=?",
                    (eid,),
                ).fetchone()
                n_fights = int(cnt_row[0] or 0)
                n_title = int(cnt_row[1] or 0)

                # Finance summary — sum amounts by sign.
                fin_row = self.conn.execute(
                    "SELECT "
                    "COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0), "
                    "COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0) "
                    "FROM finance_transactions WHERE event_id=?",
                    (eid,),
                ).fetchone()
                revenue = float(fin_row[0] or 0)
                expenses = float(fin_row[1] or 0)  # negative
                # If there's no finance data at all, leave net_profit as None
                # so the UI shows 'ledger sealed'.
                has_finance = (revenue != 0 or expenses != 0)
                net_profit = (revenue + expenses) if has_finance else None
                # Cash for the voice phrase (current_cash on promotions).
                cash_row = self.conn.execute(
                    "SELECT current_cash FROM promotions WHERE promotion_id=?",
                    (pid,),
                ).fetchone()
                current_cash = float(cash_row[0] or 0) if cash_row else 0.0

                phrase, tier_label, tier_color = self._archive_rating_phrase(rating)
                net_voice = self._archive_net_profit_voice(net_profit, current_cash)

                events.append({
                    "event_id": eid,
                    "event_name": ename or "",
                    "event_date": edate or "",
                    "event_date_display": (edate or "")[:10],
                    "venue_name": vname or "",
                    "venue_capacity": vcap,
                    "city_name": cname or "",
                    "overall_rating": rating,
                    "rating_phrase": phrase,
                    "rating_description": rating_desc or "",
                    "rating_tier_label": tier_label,
                    "rating_tier_color": tier_color,
                    "main_event": main_event,
                    "revenue": revenue if has_finance else None,
                    "expenses": expenses if has_finance else None,
                    "net_profit": net_profit,
                    "net_profit_display": _format_cash(net_profit) if net_profit is not None else "—",
                    "net_profit_voice": net_voice,
                    "n_fights": n_fights,
                    "n_title_fights": n_title,
                })

            return {
                "events": events,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "filters": {
                    "date_from": date_from or "",
                    "date_to": date_to or "",
                    "search": search,
                    "min_rating": min_rating,
                },
                "promo_id": pid,
                "promo_name": promo_name,
            }
        except Exception as e:
            print(f"[api.get_archive_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e), "events": [], "page": 1,
                    "per_page": 10, "total": 0, "total_pages": 1,
                    "filters": filters or {}}

    # ============================================================
    # P1-WIRE-4-SCREENS — Legends (Hall of Fame) screen
    # ============================================================
    # Per docs/P1_PLAN_WIRE_SCREENS.md §2 + docs/REVIEW_P1_SCREEN_BACKENDS.md
    # §3: paginated list of HoF inductees. Backed by
    # src/services/hof_svc.py (602 LOC) — the table already exists
    # (2 inductees) and is populated automatically on FIGHTER_RETIRED
    # for any fighter meeting the eligibility criteria (2+ title
    # reigns OR 30+ wins OR 20+ wins + 1+ reign).
    # ------------------------------------------------------------

    def get_hof_data(self, page=1, filters=None):
        """Return paginated Hall of Fame inductees for the Legends screen.

        Args:
          page:    int page number (20 inductees per page)
          filters: {
            "search": substring match on inductee name
            "sort":   "inducted_date_desc" (default) |
                      "inducted_date_asc" |
                      "title_reigns_desc" |
                      "wins_desc"
          }

        Returns:
          {
            "inductees": [
              {
                "fighter_id", "name", "nickname",
                "style_archetype_name",
                "inducted_date", "inducted_date_display",
                "career_summary",          # voice-layered (digit-free)
                "career_highlights",       # multi-line bullet string
                "highlights_parsed": [..], # split into list for UI
                "record_wins", "record_losses", "record_draws",
                "title_reigns",
                "has_portrait": bool,
                "portrait_uri": "data:image/…" | null
              }, ...
            ],
            "total_inductees", "page", "per_page": 20,
            "total", "total_pages", "filters"
          }
        """
        try:
            conn = self.conn
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 20

            search = (filters.get("search") or "").strip()
            sort = (filters.get("sort") or "inducted_date_desc").strip()
            # Whitelist sort options → ORDER BY clause.
            sort_map = {
                "inducted_date_desc": "h.inducted_date DESC, h.fighter_id DESC",
                "inducted_date_asc":  "h.inducted_date ASC, h.fighter_id ASC",
                "title_reigns_desc":  "COALESCE(fc.title_reigns,0) DESC, "
                                      "h.inducted_date DESC",
                "wins_desc":          "COALESCE(fc.record_wins,0) DESC, "
                                      "h.inducted_date DESC",
            }
            order_sql = sort_map.get(sort, sort_map["inducted_date_desc"])

            where_parts = []
            params = []
            if search:
                where_parts.append(
                    "(f.first_name LIKE ? OR f.last_name LIKE ? OR "
                    "(f.first_name || ' ' || f.last_name) LIKE ? OR "
                    "f.nickname LIKE ?)")
                like = f"%{search}%"
                params.extend([like, like, like, like])
            where_sql = (" WHERE " + " AND ".join(where_parts)) \
                if where_parts else ""

            # Total count.
            count_sql = (
                "SELECT COUNT(*) FROM hall_of_fame h "
                "LEFT JOIN fighters f ON f.fighter_id=h.fighter_id "
                + where_sql
            )
            total = int(conn.execute(count_sql, params).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page

            rows_sql = (
                "SELECT h.fighter_id, h.inducted_date, h.career_summary, "
                "  h.career_highlights, "
                "  f.first_name, f.last_name, f.nickname, f.portrait_path, "
                "  f.fight_style_archetype_id, "
                "  fc.record_wins, fc.record_losses, fc.record_draws, "
                "  fc.title_reigns, "
                "  sa.name "
                "FROM hall_of_fame h "
                "LEFT JOIN fighters f ON f.fighter_id=h.fighter_id "
                "LEFT JOIN fighter_career fc ON fc.fighter_id=h.fighter_id "
                "LEFT JOIN style_archetypes sa "
                "  ON sa.style_archetype_id=f.fight_style_archetype_id "
                + where_sql +
                " ORDER BY " + order_sql +
                " LIMIT ? OFFSET ?"
            )
            rows = conn.execute(rows_sql, params + [per_page, offset]).fetchall()

            inductees = []
            for r in rows:
                (fid, inducted, summary, highlights, fn, ln, nick,
                 portrait_path, style_id, wins, losses, draws, reigns,
                 style_name) = r
                name = f"{fn or ''} {ln or ''}".strip() or "Unknown"
                # Parse highlights into a list of bullet strings (strip
                # leading "• " so the UI can render its own bullets).
                highlights_parsed = []
                if highlights:
                    for line in highlights.split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("• "):
                            line = line[2:].strip()
                        elif line.startswith("•"):
                            line = line[1:].strip()
                        if line:
                            highlights_parsed.append(line)

                # Lazy portrait — only fetch if portrait_path is set.
                portrait_uri = None
                has_portrait = False
                if portrait_path:
                    pd = self.get_fighter_portrait_b64(fid)
                    if pd and pd.get("has_portrait"):
                        has_portrait = True
                        portrait_uri = pd.get("data_uri")

                inductees.append({
                    "fighter_id": fid,
                    "name": name,
                    "nickname": nick or "",
                    "style_archetype_name": style_name or "",
                    "inducted_date": inducted or "",
                    "inducted_date_display": _format_long_date(inducted),
                    "career_summary": summary or "",
                    "career_highlights": highlights or "",
                    "highlights_parsed": highlights_parsed,
                    "record_wins": int(wins or 0),
                    "record_losses": int(losses or 0),
                    "record_draws": int(draws or 0),
                    "title_reigns": int(reigns or 0),
                    "has_portrait": has_portrait,
                    "portrait_uri": portrait_uri,
                })

            return {
                "inductees": inductees,
                "total_inductees": total,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "filters": {
                    "search": search,
                    "sort": sort,
                },
            }
        except Exception as e:
            print(f"[api.get_hof_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"inductees": [], "total_inductees": 0, "page": 1,
                    "per_page": 20, "total": 0, "total_pages": 1,
                    "filters": {}, "error": str(e)}

    def get_event_card(self, event_id):
        """Return the full fight card for a single event.

        Called by The Archive when the player expands an event row.
        Returns the fights in card-slot order (main event → opener),
        with Red/Blue corners + winner highlight + result label.

        Returns:
          {
            "event_id", "event_name", "event_date",
            "fights": [
              {
                "fight_id", "card_slot", "card_slot_label",
                "is_title_fight", "is_main_event", "is_co_main",
                "weight_class_name",
                "red": {"fighter_id", "name", "nickname", "is_winner"} | null,
                "blue": {"fighter_id", "name", "nickname", "is_winner"} | null,
                "winner_id", "result_type", "result_label",
                "finish_round", "finish_time"
              }
            ]
          }
        """
        try:
            eid = int(event_id)
            ev_row = self.conn.execute(
                "SELECT event_id, event_name, event_date FROM events WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev_row:
                return {"ok": False, "error": "Event not found."}

            fights = self.conn.execute(
                "SELECT f.fight_id, f.card_slot, f.is_title_fight, "
                "f.winner_fighter_id, f.loser_fighter_id, f.result_type, "
                "f.finish_round, f.finish_time, f.weight_class_id, "
                "wc.name "
                "FROM fights f "
                "LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
                "WHERE f.event_id=? "
                "ORDER BY CASE f.card_slot "
                "  WHEN 'main_event' THEN 1 WHEN 'co_main' THEN 2 "
                "  WHEN 'featured_prelim' THEN 3 WHEN 'prelim' THEN 4 "
                "  ELSE 5 END, f.fight_id ASC",
                (eid,),
            ).fetchall()

            # Batch-fetch participants + fighter names for all fights.
            fight_ids = [r[0] for r in fights]
            parts_by_fight = {}
            if fight_ids:
                placeholders = ",".join("?" * len(fight_ids))
                part_rows = self.conn.execute(
                    "SELECT fp.fight_id, fp.fighter_id, fp.corner, fp.is_winner, "
                    "f.first_name, f.last_name, f.nickname "
                    "FROM fight_participants fp "
                    "JOIN fighters f ON f.fighter_id=fp.fighter_id "
                    f"WHERE fp.fight_id IN ({placeholders})",
                    tuple(fight_ids),
                ).fetchall()
                for (fid, fighter_id, corner, is_winner, fn, ln, nick) in part_rows:
                    parts_by_fight.setdefault(fid, {})
                    name = f"{fn or ''} {ln or ''}".strip()
                    parts_by_fight[fid][corner] = {
                        "fighter_id": fighter_id,
                        "name": name,
                        "nickname": nick or "",
                        "is_winner": bool(is_winner),
                    }

            # Card-slot labels — voice-friendly ("MAIN EVENT" / "CO-MAIN" /
            # "FEATURED PRELIM" / "PRELIM" / "OPENER"). Mirrors the
            # matchmaking screen's labels.
            slot_labels = {
                "main_event": "MAIN EVENT",
                "co_main": "CO-MAIN EVENT",
                "featured_prelim": "FEATURED PRELIM",
                "prelim": "PRELIM",
                "opener": "OPENER",
            }

            out_fights = []
            for r in fights:
                (fid, slot, is_title, wid, lid, rtype, frnd, ftime, wc_id, wc_name) = r
                parts = parts_by_fight.get(fid, {})
                red = parts.get("red")
                blue = parts.get("blue")
                # Defensive: if no participants rows, fall back to
                # winner/loser from the fights table.
                if not red and not blue:
                    if wid:
                        wf_row = self.conn.execute(
                            "SELECT first_name, last_name, nickname FROM fighters WHERE fighter_id=?",
                            (wid,),
                        ).fetchone()
                        if wf_row:
                            red = {
                                "fighter_id": wid,
                                "name": f"{wf_row[0] or ''} {wf_row[1] or ''}".strip(),
                                "nickname": wf_row[2] or "",
                                "is_winner": True,
                            }
                    if lid:
                        lf_row = self.conn.execute(
                            "SELECT first_name, last_name, nickname FROM fighters WHERE fighter_id=?",
                            (lid,),
                        ).fetchone()
                        if lf_row:
                            blue = {
                                "fighter_id": lid,
                                "name": f"{lf_row[0] or ''} {lf_row[1] or ''}".strip(),
                                "nickname": lf_row[2] or "",
                                "is_winner": False,
                            }
                out_fights.append({
                    "fight_id": fid,
                    "card_slot": slot or "prelim",
                    "card_slot_label": slot_labels.get(slot, (slot or "prelim").upper()),
                    "is_title_fight": bool(is_title),
                    "is_main_event": slot == "main_event",
                    "is_co_main": slot == "co_main",
                    "weight_class_name": wc_name or "",
                    "red": red,
                    "blue": blue,
                    "winner_id": wid,
                    "result_type": rtype or "",
                    "result_label": _result_type_label(rtype),
                    "finish_round": frnd,
                    "finish_time": ftime or "",
                })

            return {
                "event_id": ev_row[0],
                "event_name": ev_row[1] or "",
                "event_date": ev_row[2] or "",
                "fights": out_fights,
            }
        except Exception as e:
            print(f"[api.get_event_card] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e), "fights": []}

    # ============================================================
    # FIGHT NIGHT — live play-by-play (Task FIGHT-NIGHT-SHOWCASE)
    # ============================================================
    #
    # Per docs/RESEARCH_FIGHT_NIGHT.md §7 + CONVENTIONS §17.2:
    # Fight Night is EXEMPT from the snapshot-cache rule and reads
    # live `fight_beats` / `fight_rounds` / `commentary_segments` /
    # `matchup_analyses` tables directly. The voice layer is applied
    # on the fly per beat (the per-beat commentary is generated at
    # resolution time by `_generate_per_beat_commentary` in
    # services/fight_engine.py).
    #
    # Three methods:
    #   1. resolve_next_fight(event_id=None) — resolves ONE fight
    #      on the player's scheduled event. The engine picks the
    #      lowest-fight_id unresolved fight on the player's promo
    #      (rival AI is explicitly excluded — see RESEARCH_FIGHT_NIGHT
    #      §1.4). Returns the full result payload + beats + commentary.
    #   2. get_fight_night_data(fight_id=None) — returns the full
    #      play-by-play payload for a fight (resolved or, in preview
    #      mode, unresolved). For resolved fights: fight_beats +
    #      commentary_segments + fight_rounds + result card. For
    #      unresolved fights: just pre-fight data (tale of tape +
    #      punditry + rivalry context) so the UI can render the
    #      pre-fight build-up phase.
    #   3. get_event_fights(event_id) — returns all fights on an
    #      event with their resolution status + result info, for
    #      the "Fight X of Y" transport bar.

    def resolve_next_fight(self, event_id=None):
        """Resolve the next unresolved fight on the player's scheduled event.

        The engine (`services.fight_engine.resolve_next_fight`) picks
        the lowest-fight_id unresolved fight on the player's promotion.
        The player's promotion is explicitly excluded from rival-AI
        auto-resolution (RESEARCH_FIGHT_NIGHT §1.4), so this is the
        ONLY way the player's booked fights resolve in the web UI.

        The event_id param is informational — it lets the UI display
        "Fight N of M on Event X" after resolution. The engine still
        picks the lowest-id unresolved fight on the player's promo
        (which is almost always on the player's next scheduled event).
        If event_id is provided AND the resolved fight is on a
        different event, the response includes a `different_event`
        flag so the UI can inform the player.

        Returns:
          {
            "ok": True|False,
            "reason": "no_fights"|"cancelled"|"resolved",  # only when ok=False or special
            "fight_id", "event_id",
            "winner_id", "loser_id", "winner_name", "loser_name",
            "result_type", "result_phrase",  # voice phrase ("KO/TKO", "submission", etc.)
            "finish_round", "finish_time",
            "performance_rating_phrase",  # voice phrase (no raw number per §14)
            "fan_reaction_rating_phrase",  # voice phrase
            "is_title_fight", "title_changed",
            "injuries": [...],  # post-fight injury rows (voice-phrased)
            "news_headline", "news_body",
            "beats_count", "commentary_count",
            "different_event": bool  # only present if event_id was provided
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}

            # P3.2 (docs/COMPREHENSIVE_FIX_PLAN.md §Group D #15) —
            # Fights can ONLY be resolved on the event's scheduled
            # date. The Fight Night screen is now "Watch the Show"
            # (Dashboard/Calendar entry only); there's no sidebar
            # entry, so the player can't cheat-resolve fights before
            # the event. This server-side check is the canonical
            # enforcement — the UI hint is secondary.
            #
            # Two cases:
            #   1. event_id provided — verify it belongs to the
            #      player's promo AND its event_date == sim_date.
            #      If sim_date < event_date: "Your event is scheduled
            #      for [date]. Advance the sim to that day first."
            #      If sim_date > event_date: the event should already
            #      have been resolved (rival AI auto-resolves past
            #      events on tick). Defensive — surface the same hint.
            #   2. event_id is None — find the player's next scheduled
            #      event whose event_date == sim_date. If none, tell
            #      the player no event is scheduled today.
            clock_row = get_clock(self.conn)
            sim_date = clock_row[0] if clock_row else None

            target_event_id = None
            target_event_date = None
            if event_id is not None:
                try:
                    req_eid = int(event_id)
                except (ValueError, TypeError):
                    return {"ok": False,
                            "error": "Invalid event_id."}
                ev_row = self.conn.execute(
                    "SELECT event_id, event_date, promotion_id, status "
                    "FROM events WHERE event_id=?",
                    (req_eid,),
                ).fetchone()
                if not ev_row:
                    return {"ok": False,
                            "error": "Event not found."}
                (req_event_id, req_event_date, req_promo_id,
                 req_status) = ev_row
                if req_promo_id != pid:
                    return {"ok": False,
                            "error": "This event belongs to another promotion."}
                if req_event_date != sim_date:
                    # Voice-compliant hint per the brief.
                    fmt_date = _format_long_date(req_event_date)
                    return {
                        "ok": False,
                        "reason": "wrong_day",
                        "event_id": req_event_id,
                        "event_date": req_event_date or "",
                        "sim_date": sim_date or "",
                        "message": (
                            f"Your event is scheduled for {fmt_date}. "
                            f"Advance the sim to that day first."
                        ),
                    }
                target_event_id = req_event_id
                target_event_date = req_event_date
            else:
                # No event_id provided — find the player's scheduled
                # event whose event_date == sim_date. If none, tell
                # the player no event is scheduled today (so they
                # don't sit on a dead Fight Night screen wondering
                # why nothing happens).
                ev_row = self.conn.execute(
                    "SELECT event_id, event_date FROM events "
                    "WHERE promotion_id=? AND event_date=? "
                    "AND status IN ('scheduled','card_confirmed','in_progress') "
                    "ORDER BY event_id LIMIT 1",
                    (pid, sim_date),
                ).fetchone()
                if not ev_row:
                    return {
                        "ok": False,
                        "reason": "no_event_today",
                        "sim_date": sim_date or "",
                        "message": (
                            "No event scheduled today. Check the Calendar."
                        ),
                    }
                target_event_id = ev_row[0]
                target_event_date = ev_row[1]

            from services.fight_engine import resolve_next_fight as _resolve
            fight_id = _resolve(self.conn, promotion_id=pid)
            if fight_id is None:
                # No unresolved fights on the player's promo.
                # Distinguish "all fights on this event resolved" from
                # "no unresolved fights anywhere" so the player gets a
                # useful message.
                if target_event_id:
                    n = self.conn.execute(
                        "SELECT COUNT(*) FROM fights WHERE event_id=? "
                        "AND winner_fighter_id IS NULL AND result_type IS NULL",
                        (target_event_id,),
                    ).fetchone()[0]
                    if n == 0:
                        return {"ok": False, "reason": "no_fights",
                                "message": "All fights on this card have been resolved."}
                return {"ok": False, "reason": "no_fights",
                        "message": "No unresolved fights on your schedule."}
            self.conn.commit()

            # Read the resolved fight's data.
            row = self.conn.execute(
                "SELECT f.event_id, f.is_title_fight, f.weight_class_id, "
                "f.winner_fighter_id, f.loser_fighter_id, "
                "f.result_type, f.finish_round, f.finish_time, "
                "f.performance_rating, f.fan_reaction_rating, "
                "e.event_name, e.event_date "
                "FROM fights f JOIN events e ON e.event_id=f.event_id "
                "WHERE f.fight_id=?",
                (fight_id,),
            ).fetchone()
            if not row:
                # P3.1 — surface the actual failure rather than the
                # generic "Could not resolve this fight." the JS falls
                # back to. The player/dev can then trace the cause.
                return {"ok": False,
                        "error": "Resolved fight not found (fight_id={}).".format(
                            fight_id),
                        "message": "The fight was resolved but could not be loaded."}
            (ev_id, is_title, wc_id, winner_id, loser_id, rtype,
             finish_round, finish_time, perf, fan_react,
             event_name, event_date) = row

            # Detect cancellation (no_contest from weight-cut miss).
            if rtype == "no_contest":
                return {
                    "ok": True, "reason": "cancelled",
                    "fight_id": fight_id, "event_id": ev_id,
                    "event_name": event_name or "",
                    "result_type": "no_contest",
                    "result_phrase": "cancelled (no contest)",
                    "winner_id": None, "loser_id": None,
                    "winner_name": None, "loser_name": None,
                    "finish_round": 0, "finish_time": "0:00",
                    "is_title_fight": bool(is_title),
                    "title_changed": False,
                    "injuries": [],
                    "news_headline": "Fight cancelled — weight cut missed.",
                    "news_body": "The fight has been cancelled due to a weight miss.",
                    "beats_count": 0, "commentary_count": 0,
                }

            winner_name = (loser_name) = ""
            if winner_id:
                wr = self.conn.execute(
                    "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?",
                    (winner_id,),
                ).fetchone()
                winner_name = wr[0] if wr else ""
            if loser_id:
                lr = self.conn.execute(
                    "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?",
                    (loser_id,),
                ).fetchone()
                loser_name = lr[0] if lr else ""

            # Beats + commentary counts.
            beats_count = self.conn.execute(
                "SELECT COUNT(*) FROM fight_beats WHERE fight_id=?",
                (fight_id,),
            ).fetchone()[0]
            commentary_count = self.conn.execute(
                "SELECT COUNT(*) FROM commentary_segments WHERE fight_id=?",
                (fight_id,),
            ).fetchone()[0]

            # News item for this fight (if any).
            news = self.conn.execute(
                "SELECT headline, body FROM news_items "
                "WHERE fight_id=? ORDER BY published_at DESC LIMIT 1",
                (fight_id,),
            ).fetchone()
            news_headline = news[0] if news else ""
            news_body = news[1] if news else ""

            # Title change detection.
            title_changed = False
            if is_title:
                tc = self.conn.execute(
                    "SELECT 1 FROM news_items WHERE fight_id=? AND topic='title' "
                    "ORDER BY published_at DESC LIMIT 1",
                    (fight_id,),
                ).fetchone()
                # A title-change news item is written by the news engine
                # when a belt changes hands. If a 'title' topic news item
                # exists for this fight, we infer title_changed=True.
                title_changed = tc is not None

            # Post-fight injuries for either fighter.
            injuries = []
            inj_rows = self.conn.execute(
                "SELECT fighter_id, injury_type, body_area, severity, "
                "projected_return_date "
                "FROM injuries WHERE fight_id=? AND is_active=1",
                (fight_id,),
            ).fetchall()
            for (inj_fid, inj_type, body_area, severity, ret_date) in inj_rows:
                inj_name = self.conn.execute(
                    "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?",
                    (inj_fid,),
                ).fetchone()
                injuries.append({
                    "fighter_id": inj_fid,
                    "fighter_name": inj_name[0] if inj_name else "",
                    "injury_type": inj_type or "",
                    "body_area": body_area or "",
                    "severity_phrase": _severity_phrase_for_injury(severity),
                    "projected_return_date": ret_date or "",
                })

            # Build response.
            resp = {
                "ok": True, "reason": "resolved",
                "fight_id": fight_id, "event_id": ev_id,
                "event_name": event_name or "",
                "event_date": event_date or "",
                "winner_id": winner_id, "loser_id": loser_id,
                "winner_name": winner_name, "loser_name": loser_name,
                "result_type": rtype or "decision",
                "result_phrase": _result_type_label(rtype),
                "finish_round": finish_round or 0,
                "finish_time": finish_time or "",
                "performance_rating_phrase": _rating_voice_phrase(perf, "performance"),
                "fan_reaction_rating_phrase": _rating_voice_phrase(fan_react, "fan"),
                "is_title_fight": bool(is_title),
                "title_changed": title_changed,
                "injuries": injuries,
                "news_headline": news_headline,
                "news_body": news_body,
                "beats_count": beats_count,
                "commentary_count": commentary_count,
            }
            # If event_id was provided and the resolved fight is on a
            # different event, flag it (the UI may show an info banner).
            if event_id is not None:
                try:
                    req_eid = int(event_id)
                    resp["different_event"] = (req_eid != ev_id)
                    resp["requested_event_id"] = req_eid
                except (ValueError, TypeError):
                    pass
            return resp
        except Exception as e:
            print(f"[api.resolve_next_fight] {e}\n{traceback.format_exc()}",
                  flush=True)
            # P3.1 — surface the actual exception text in BOTH `error`
            # (programmatic) AND `message` (UI-displayable) so the JS
            # doesn't fall back to the generic "Could not resolve this
            # fight." string. The user's "Unable to resolve fight"
            # complaint was often a Python exception silently swallowed
            # by the catch block — now the player sees the cause.
            return {"ok": False, "error": str(e),
                    "message": "Could not resolve this fight: " + str(e)}

    def get_fight_night_data(self, fight_id=None):
        """Return the full play-by-play payload for a fight.

        If fight_id is None: returns the NEXT unresolved fight on the
        player's promotion (preview mode — no resolution). The UI uses
        this for the pre-fight build-up phase before the player clicks
        "Play".

        If fight_id is provided: returns the full data for that fight,
        including all fight_beats + commentary_segments + fight_rounds
        + result card (for resolved fights) or just the pre-fight data
        (for unresolved fights — replay or pre-booked-fight preview).

        Returns:
          {
            "ok": True|False,
            "fight_id", "event_id", "is_resolved",
            "fight": {  # fight metadata
              "fight_id", "event_id", "scheduled_rounds", "card_slot",
              "card_slot_label", "is_title_fight", "weight_class_name"
            },
            "event": {  # parent event metadata
              "event_id", "event_name", "event_date", "promotion_name",
              "venue_name"
            },
            "red": {  # full fighter brief + portrait (data URI)
              ... (see _fighter_brief), + "portrait_data_uri"
            },
            "blue": { ... },
            "rivalry": {  # rivalry context (if exists between these two)
              "rivalry_heat", "rivalry_type_label", "fights_count",
              "fighter_a_wins", "fighter_b_wins", "draws",
              "origin_description"
            } | null,
            "previous_meetings": [  # fight_history rows between these two
              {"fight_id", "event_date", "outcome_red", "result_type",
               "finish_round"}
            ],
            "matchup_analysis": {  # punditry pre-fight analysis (if exists)
              "predicted_winner", "predicted_method", "confidence_pct",
              "style_edge", "excitement_score", "upset_risk",
              "analysis_text"
            } | null,
            "beats": [  # fight_beats rows (resolved only) — chronological
              {"fight_beat_id", "round_number", "beat_number", "phase",
               "action_type", "initiator_fighter_id",
               "target_fighter_id", "initiator_name", "target_name",
               "outcome", "damage_dealt", "control_time_delta",
               "momentum_shift", "commentary_text"}
            ],
            "rounds": [  # fight_rounds rows (resolved only)
              {"round_number", "fighter_a_id", "fighter_b_id",
               "fighter_a_damage", "fighter_b_damage",
               "fighter_a_strikes_landed", "fighter_b_strikes_landed",
               "fighter_a_takedowns", "fighter_b_takedowns",
               "fighter_a_knockdowns", "fighter_b_knockdowns",
               "fighter_a_gas_remaining", "fighter_b_gas_remaining",
               "round_winner_fighter_id"}
            ],
            "highlights": [  # commentary_segments WHERE segment_type='highlight'
              {"text", "importance"}
            ],
            "play_by_play": "",  # commentary_segments WHERE segment_type='play_by_play' (overall summary)
            "result": {  # fight result card (resolved only)
              "winner_id", "loser_id", "winner_name", "loser_name",
              "result_type", "result_phrase", "finish_round",
              "finish_time", "performance_rating_phrase",
              "fan_reaction_rating_phrase", "is_title_fight",
              "title_changed"
            } | null,
            "show_rating": {  # only when the event is completed
              "overall_rating_phrase", "rating_description",
              "fan_rating", "commercial_rating", "excitement_rating",
              "quality_rating", "overall_rating"
            } | null,
            "next_unresolved_fight_id": int|null,  # for the "Next Fight" button
            "is_last_fight_on_card": bool
          }
        """
        try:
            pid = self.get_player_promotion()
            conn = self.conn

            # Resolve which fight to load.
            if fight_id is None:
                # Preview mode — find the next unresolved fight on the
                # player's promo. P3.3 — order by card_slot ASC so
                # prelims play first, main event LAST. (Previously
                # ORDER BY f.fight_id picked the main_event first
                # because confirm_card assigns main_event at idx=0.)
                row = conn.execute(
                    "SELECT f.fight_id FROM fights f "
                    "JOIN events e ON e.event_id=f.event_id "
                    "WHERE f.winner_fighter_id IS NULL "
                    "AND f.result_type IS NULL "
                    "AND e.promotion_id=? "
                    "ORDER BY CASE f.card_slot "
                    "  WHEN 'opener' THEN 1 "
                    "  WHEN 'prelim' THEN 2 "
                    "  WHEN 'featured_prelim' THEN 3 "
                    "  WHEN 'co_main' THEN 4 "
                    "  WHEN 'main_event' THEN 5 "
                    "  ELSE 6 END, f.fight_id ASC LIMIT 1",
                    (pid,),
                ).fetchone()
                if not row:
                    # P3.2 — distinguish "no event today" from "no
                    # unresolved fights" so the dashboard hint matches
                    # the resolve_next_fight API's messaging.
                    clock_row = get_clock(conn)
                    sim_date = clock_row[0] if clock_row else None
                    has_event_today = conn.execute(
                        "SELECT 1 FROM events WHERE promotion_id=? "
                        "AND event_date=? "
                        "AND status IN ('scheduled','card_confirmed','in_progress') "
                        "LIMIT 1",
                        (pid, sim_date),
                    ).fetchone()
                    if not has_event_today:
                        return {"ok": False, "reason": "no_event_today",
                                "sim_date": sim_date or "",
                                "message": "No event scheduled today. Check the Calendar."}
                    return {"ok": False, "reason": "no_fights",
                            "message": "No unresolved fights on your schedule."}
                fid = row[0]
            else:
                try:
                    fid = int(fight_id)
                except (ValueError, TypeError):
                    return {"ok": False, "error": "Invalid fight_id."}

            # Fight + event metadata.
            frow = conn.execute(
                "SELECT f.fight_id, f.event_id, f.scheduled_rounds, "
                "f.card_slot, f.is_title_fight, f.weight_class_id, "
                "f.winner_fighter_id, f.loser_fighter_id, "
                "f.result_type, f.finish_round, f.finish_time, "
                "f.performance_rating, f.fan_reaction_rating, "
                "wc.name, "
                "e.event_name, e.event_date, e.venue_id, "
                "p.name AS promo_name, "
                "v.name AS venue_name "
                "FROM fights f "
                "JOIN events e ON e.event_id=f.event_id "
                "LEFT JOIN weight_classes wc "
                "  ON wc.weight_class_id=f.weight_class_id "
                "LEFT JOIN promotions p ON p.promotion_id=e.promotion_id "
                "LEFT JOIN venues v ON v.venue_id=e.venue_id "
                "WHERE f.fight_id=?",
                (fid,),
            ).fetchone()
            if not frow:
                return {"ok": False, "error": "Fight not found."}
            (fid2, ev_id, sched_rounds, card_slot, is_title, wc_id,
             winner_id, loser_id, rtype, frnd, ftime, perf, fan_react,
             wc_name, event_name, event_date, venue_id,
             promo_name, venue_name) = frow

            is_resolved = (winner_id is not None) or (rtype is not None)

            # Get participants (red corner first).
            parts = conn.execute(
                "SELECT fighter_id, corner FROM fight_participants "
                "WHERE fight_id=? ORDER BY corner",
                (fid,),
            ).fetchall()
            red_id = None
            blue_id = None
            for (p_fid, p_corner) in parts:
                if p_corner == "red":
                    red_id = p_fid
                elif p_corner == "blue":
                    blue_id = p_fid
            if not red_id or not blue_id:
                return {"ok": False, "error": "Fight has incomplete participants."}

            # Fighter briefs + portraits.
            red_brief = self._fighter_brief(conn, red_id) or {}
            blue_brief = self._fighter_brief(conn, blue_id) or {}
            red_brief["portrait_data_uri"] = self._portrait_data_uri(red_id)
            blue_brief["portrait_data_uri"] = self._portrait_data_uri(blue_id)

            # Rivalry context (if any).
            rivalry = None
            rrow = conn.execute(
                "SELECT rivalry_heat, rivalry_type, fights_count, "
                "fighter_a_wins, fighter_b_wins, draws, origin_description, "
                "fighter_a_id, fighter_b_id "
                "FROM rivalries "
                "WHERE (fighter_a_id=? AND fighter_b_id=?) "
                "OR (fighter_a_id=? AND fighter_b_id=?)",
                (red_id, blue_id, blue_id, red_id),
            ).fetchone()
            if rrow:
                (heat, rtype_riv, n_fights, a_wins, b_wins, draws,
                 origin_desc, ra_id, rb_id) = rrow
                # Translate a_wins/b_wins to red/blue perspective.
                if ra_id == red_id:
                    red_wins, blue_wins = a_wins, b_wins
                else:
                    red_wins, blue_wins = b_wins, a_wins
                rivalry = {
                    "rivalry_heat": heat or 50,
                    "rivalry_type_label": _rivalry_type_label(
                        rtype_riv, heat, n_fights, red_wins, blue_wins, draws,
                    ),
                    "fights_count": n_fights or 0,
                    "red_wins": red_wins,
                    "blue_wins": blue_wins,
                    "draws": draws or 0,
                    "origin_description": origin_desc or "",
                    "bad_blood": (heat or 0) >= 50,
                }

            # Previous meetings (fight_history rows between these two
            # fighters, regardless of which fight_id they were on).
            previous_meetings = []
            pm_rows = conn.execute(
                "SELECT fh.fight_id, fh.event_date, fh.outcome, "
                "fh.result_type, fh.finish_round, "
                "fh.fighter_id, fh.opponent_id "
                "FROM fight_history fh "
                "WHERE (fh.fighter_id=? AND fh.opponent_id=?) "
                "OR (fh.fighter_id=? AND fh.opponent_id=?) "
                "ORDER BY fh.event_date DESC LIMIT 5",
                (red_id, blue_id, blue_id, red_id),
            ).fetchall()
            seen_fight_ids = set()
            for (pm_fid, pm_date, pm_outcome, pm_rtype, pm_frnd,
                 pm_self, pm_opp) in pm_rows:
                if pm_fid in seen_fight_ids or pm_fid == fid:
                    continue
                seen_fight_ids.add(pm_fid)
                # Translate outcome to red perspective.
                if pm_self == red_id:
                    red_outcome = pm_outcome
                else:
                    # Flip win/loss for the blue perspective.
                    flip = {"win": "loss", "loss": "win",
                            "draw": "draw", "nc": "nc"}
                    red_outcome = flip.get(pm_outcome, pm_outcome)
                previous_meetings.append({
                    "fight_id": pm_fid,
                    "event_date": pm_date or "",
                    "outcome_red": red_outcome,
                    "result_type": pm_rtype or "",
                    "result_phrase": _result_type_label(pm_rtype),
                    "finish_round": pm_frnd or 0,
                })

            # Punditry matchup_analysis (if exists for this fight).
            matchup_analysis = None
            ma_row = conn.execute(
                "SELECT predicted_winner, predicted_method, confidence_pct, "
                "style_edge, excitement_score, upset_risk, analysis_text "
                "FROM matchup_analyses WHERE fight_id=? LIMIT 1",
                (fid,),
            ).fetchone()
            if ma_row:
                matchup_analysis = {
                    "predicted_winner": ma_row[0] or "",
                    "predicted_method": ma_row[1] or "",
                    "confidence_pct": ma_row[2] or 50,
                    "style_edge": ma_row[3] or "",
                    "excitement_score": ma_row[4] or 50,
                    "upset_risk": ma_row[5] or "",
                    "analysis_text": ma_row[6] or "",
                }

            # Beats (resolved only). Fetched separately from
            # commentary_segments to avoid the JOIN duplicating beat
            # rows (1 beat × N commentary_segments = N beat rows in
            # the result set, which corrupted the beat count).
            beats = []
            if is_resolved:
                beat_rows = conn.execute(
                    "SELECT fb.fight_beat_id, fb.round_number, fb.beat_number, "
                    "fb.phase, fb.action_type, "
                    "fb.initiator_fighter_id, fb.target_fighter_id, "
                    "fb.outcome, fb.damage_dealt, fb.control_time_delta, "
                    "fb.momentum_shift, "
                    "fa.first_name || ' ' || fa.last_name AS init_name, "
                    "ft.first_name || ' ' || ft.last_name AS tgt_name "
                    "FROM fight_beats fb "
                    "JOIN fighters fa "
                    "  ON fa.fighter_id=fb.initiator_fighter_id "
                    "JOIN fighters ft "
                    "  ON ft.fighter_id=fb.target_fighter_id "
                    "WHERE fb.fight_id=? "
                    "ORDER BY fb.round_number, fb.beat_number",
                    (fid,),
                ).fetchall()
                # Fetch per-beat commentary in the same order — the
                # per-beat commentary is written by
                # _generate_per_beat_commentary in beat order, so the
                # Nth 'beat' segment corresponds to the Nth beat.
                beat_seg_rows = conn.execute(
                    "SELECT text FROM commentary_segments "
                    "WHERE fight_id=? AND segment_type='beat' "
                    "ORDER BY commentary_segment_id",
                    (fid,),
                ).fetchall()
                beat_seg_texts = [r[0] for r in beat_seg_rows]
                for i, b in enumerate(beat_rows):
                    (bid, rn, bn, phase, action, init_id, tgt_id,
                     outcome, dmg, ctrl, mom, init_name, tgt_name) = b
                    commentary_text = (beat_seg_texts[i]
                                       if i < len(beat_seg_texts) else "")
                    beats.append({
                        "fight_beat_id": bid,
                        "round_number": rn, "beat_number": bn,
                        "phase": phase, "action_type": action,
                        "initiator_fighter_id": init_id,
                        "target_fighter_id": tgt_id,
                        "initiator_name": init_name,
                        "target_name": tgt_name,
                        "outcome": outcome,
                        "damage_dealt": dmg,
                        "control_time_delta": ctrl,
                        "momentum_shift": mom,
                        "commentary_text": commentary_text,
                    })

            # Rounds (resolved only).
            rounds = []
            if is_resolved:
                rrows = conn.execute(
                    "SELECT round_number, fighter_a_id, fighter_b_id, "
                    "fighter_a_damage, fighter_b_damage, "
                    "fighter_a_strikes_landed, fighter_b_strikes_landed, "
                    "fighter_a_takedowns, fighter_b_takedowns, "
                    "fighter_a_knockdowns, fighter_b_knockdowns, "
                    "fighter_a_gas_remaining, fighter_b_gas_remaining, "
                    "round_winner_fighter_id "
                    "FROM fight_rounds WHERE fight_id=? "
                    "ORDER BY round_number",
                    (fid,),
                ).fetchall()
                for r in rrows:
                    rounds.append({
                        "round_number": r[0],
                        "fighter_a_id": r[1], "fighter_b_id": r[2],
                        "fighter_a_damage": r[3], "fighter_b_damage": r[4],
                        "fighter_a_strikes_landed": r[5],
                        "fighter_b_strikes_landed": r[6],
                        "fighter_a_takedowns": r[7],
                        "fighter_b_takedowns": r[8],
                        "fighter_a_knockdowns": r[9],
                        "fighter_b_knockdowns": r[10],
                        "fighter_a_gas_remaining": r[11],
                        "fighter_b_gas_remaining": r[12],
                        "round_winner_fighter_id": r[13],
                        # Convenience flag: did red win this round?
                        "red_won": (r[13] == red_id),
                    })

            # Highlights (commentary_segments WHERE segment_type='highlight').
            highlights = []
            if is_resolved:
                hrows = conn.execute(
                    "SELECT text, importance FROM commentary_segments "
                    "WHERE fight_id=? AND segment_type='highlight' "
                    "ORDER BY commentary_segment_id",
                    (fid,),
                ).fetchall()
                for h in hrows:
                    highlights.append({"text": h[0], "importance": h[1]})

            # P3.5 — extra commentary segments (announcer / pundit /
            # crowd). These are interleaved with the per-beat 'beat'
            # segments in Zone A of the Fight Night screen. Each row
            # has a segment_type that drives the CSS styling, and a
            # beat_index that tells the UI WHERE to insert it relative
            # to the beat rows:
            #   - beat_index = -1: before the first beat (announcer intro)
            #   - beat_index = N:  after the Nth beat (0-indexed)
            # The beat_index is derived from the segment's
            # commentary_segment_id relative to the 'beat' segments'
            # IDs — the 'beat' segments are written in beat order, so
            # a segment written AFTER beat N's row but BEFORE beat
            # N+1's row belongs to beat_index N.
            extra_segments = []
            if is_resolved:
                # Pull all non-'beat'/non-'highlight'/non-'play_by_play'
                # segments in insertion order. The segment_type tells
                # the UI which CSS class to use.
                ex_rows = conn.execute(
                    "SELECT commentary_segment_id, segment_type, "
                    "speaker_staff_id, text, importance "
                    "FROM commentary_segments "
                    "WHERE fight_id=? "
                    "AND segment_type IN ('announcer','pundit','crowd') "
                    "ORDER BY commentary_segment_id",
                    (fid,),
                ).fetchall()
                # Pull the 'beat' segments' IDs so we can compute
                # beat_index for each extra segment.
                beat_ids_rows = conn.execute(
                    "SELECT commentary_segment_id FROM commentary_segments "
                    "WHERE fight_id=? AND segment_type='beat' "
                    "ORDER BY commentary_segment_id",
                    (fid,),
                ).fetchall()
                beat_ids = [r[0] for r in beat_ids_rows]
                # Speaker name lookup cache.
                speaker_cache = {}
                def speaker_name_of(sid):
                    if sid is None:
                        return ""
                    if sid not in speaker_cache:
                        srow = conn.execute(
                            "SELECT first_name, last_name FROM staff "
                            "WHERE staff_id=?",
                            (sid,),
                        ).fetchone()
                        if srow:
                            speaker_cache[sid] = (
                                (srow[0] or "") + " " + (srow[1] or "")
                            ).strip()
                        else:
                            speaker_cache[sid] = ""
                    return speaker_cache[sid]
                for ex in ex_rows:
                    (ex_sid, ex_type, ex_speaker_id, ex_text,
                     ex_imp) = ex
                    # Compute beat_index: count how many beat IDs are
                    # strictly less than this segment's ID. The
                    # announcer intro is written BEFORE any beat, so
                    # its beat_index = 0 (it appears before beat 0).
                    # Wait — actually we want announcer to appear
                    # BEFORE the first beat, so its beat_index = -1
                    # (the UI inserts it at the top). Pundit/crowd
                    # segments are written AFTER a beat, so their
                    # beat_index = the index of the beat they follow.
                    n_before = sum(1 for bid in beat_ids if bid < ex_sid)
                    if ex_type == "announcer":
                        beat_idx = -1
                    else:
                        # n_before = number of beats written before
                        # this extra segment = the index of the beat
                        # this segment FOLLOWS (0-indexed).
                        beat_idx = max(0, n_before - 1)
                    extra_segments.append({
                        "segment_type": ex_type,
                        "speaker_name": speaker_name_of(ex_speaker_id),
                        "text": ex_text or "",
                        "importance": ex_imp or 50,
                        "beat_index": beat_idx,
                    })

            # Play-by-play (overall summary, segment_type='play_by_play').
            play_by_play = ""
            if is_resolved:
                pbp_row = conn.execute(
                    "SELECT text FROM commentary_segments "
                    "WHERE fight_id=? AND segment_type='play_by_play' "
                    "ORDER BY commentary_segment_id LIMIT 1",
                    (fid,),
                ).fetchone()
                if pbp_row:
                    play_by_play = pbp_row[0]

            # Result card.
            result = None
            if is_resolved and rtype != "no_contest":
                winner_name = ""
                loser_name = ""
                if winner_id:
                    wr = conn.execute(
                        "SELECT first_name || ' ' || last_name "
                        "FROM fighters WHERE fighter_id=?",
                        (winner_id,),
                    ).fetchone()
                    winner_name = wr[0] if wr else ""
                if loser_id:
                    lr = conn.execute(
                        "SELECT first_name || ' ' || last_name "
                        "FROM fighters WHERE fighter_id=?",
                        (loser_id,),
                    ).fetchone()
                    loser_name = lr[0] if lr else ""
                # Title change detection (same as resolve_next_fight).
                title_changed = False
                if is_title:
                    tc = conn.execute(
                        "SELECT 1 FROM news_items WHERE fight_id=? "
                        "AND topic='title' LIMIT 1",
                        (fid,),
                    ).fetchone()
                    title_changed = tc is not None

                # P3.6 — ranking change phrases. Compute the winner's
                # + loser's current rank in their WC (post-fight), then
                # phrase the change. The "rises to #N" / "drops to #N"
                # language is voice-compliant (no raw ELO numbers per
                # §14). Falls back to null if the fighter is unranked
                # (>15) or has no rankings row.
                def _rank_phrase(fighter_id, fighter_name, is_winner):
                    if not fighter_id or not fighter_name:
                        return None
                    rrow = conn.execute(
                        "SELECT r.rating, r.weight_class_id, "
                        "f.current_promotion_id "
                        "FROM rankings r JOIN fighters f "
                        "ON f.fighter_id=r.fighter_id "
                        "WHERE r.fighter_id=?",
                        (fighter_id,),
                    ).fetchone()
                    if not rrow:
                        return None
                    rating, fwc_id, fpromo_id = rrow
                    if not fwc_id:
                        return None
                    rank_row = conn.execute(
                        "SELECT COUNT(*) + 1 FROM rankings r2 "
                        "WHERE r2.weight_class_id=? "
                        "AND r2.promotion_id=? "
                        "AND r2.rating > ?",
                        (fwc_id, fpromo_id, rating or 1000.0),
                    ).fetchone()
                    if not rank_row:
                        return None
                    rank_int = int(rank_row[0])
                    if rank_int > 15:
                        return None  # unranked — no phrase
                    if is_winner:
                        verb = "rises to" if rank_int <= 5 else "climbs to"
                    else:
                        verb = "drops to" if rank_int <= 10 else "falls to"
                    return f"{fighter_name} {verb} #{rank_int} in the division"

                ranking_change_winner = _rank_phrase(
                    winner_id, winner_name, True)
                ranking_change_loser = _rank_phrase(
                    loser_id, loser_name, False)

                # P3.6 — voice-phrased result method. The existing
                # _result_type_label returns "KO/TKO", "Submission",
                # etc. — terse, sports-page register. The recap screen
                # wants more visceral language: "by devastating
                # knockout", "by rear-naked choke", etc. The
                # method_phrase_voice slot is filled here, the UI
                # uses it in the result card.
                method_phrase_voice = _result_method_voice_phrase(
                    rtype, frnd, ftime)

                # P3.6 — post-fight injuries. The resolve_next_fight
                # API already returns these, but get_fight_night_data
                # (used in replay mode + the recap screen) didn't
                # include them. Query the injuries table directly.
                fight_injuries = []
                inj_rows = conn.execute(
                    "SELECT fighter_id, injury_type, body_area, "
                    "severity, projected_return_date "
                    "FROM injuries WHERE fight_id=? AND is_active=1",
                    (fid,),
                ).fetchall()
                for (inj_fid, inj_type, body_area, severity,
                     ret_date) in inj_rows:
                    inj_name = conn.execute(
                        "SELECT first_name || ' ' || last_name "
                        "FROM fighters WHERE fighter_id=?",
                        (inj_fid,),
                    ).fetchone()
                    fight_injuries.append({
                        "fighter_id": inj_fid,
                        "fighter_name": inj_name[0] if inj_name else "",
                        "injury_type": inj_type or "",
                        "body_area": body_area or "",
                        "severity_phrase": _severity_phrase_for_injury(
                            severity),
                        "projected_return_date": ret_date or "",
                    })

                # P3.6 — news item for this fight. The recap screen
                # shows the headline + body so the player sees the
                # story the wire is running. Prefer topic='fight' (the
                # post-fight recap story); fall back to the most
                # recent news item of any topic for this fight
                # (weight-cut, title, injury, etc.) so the recap
                # always has SOMETHING to show.
                news_headline = ""
                news_body = ""
                news_row = conn.execute(
                    "SELECT headline, body FROM news_items "
                    "WHERE fight_id=? AND topic='fight' "
                    "ORDER BY published_at DESC LIMIT 1",
                    (fid,),
                ).fetchone()
                if not news_row:
                    news_row = conn.execute(
                        "SELECT headline, body FROM news_items "
                        "WHERE fight_id=? "
                        "ORDER BY published_at DESC LIMIT 1",
                        (fid,),
                    ).fetchone()
                if news_row:
                    news_headline = news_row[0] or ""
                    news_body = news_row[1] or ""

                result = {
                    "winner_id": winner_id, "loser_id": loser_id,
                    "winner_name": winner_name, "loser_name": loser_name,
                    "result_type": rtype or "decision",
                    "result_phrase": _result_type_label(rtype),
                    "method_phrase_voice": method_phrase_voice,
                    "finish_round": frnd or 0,
                    "finish_time": ftime or "",
                    "performance_rating_phrase": _rating_voice_phrase(
                        perf, "performance"),
                    "fan_reaction_rating_phrase": _rating_voice_phrase(
                        fan_react, "fan"),
                    "is_title_fight": bool(is_title),
                    "title_changed": title_changed,
                    "ranking_change_winner": ranking_change_winner,
                    "ranking_change_loser": ranking_change_loser,
                    "injuries": fight_injuries,
                    "news_headline": news_headline,
                    "news_body": news_body,
                }

            # Show rating (only if the event is completed).
            show_rating = None
            sr_row = conn.execute(
                "SELECT fan_rating, commercial_rating, excitement_rating, "
                "quality_rating, overall_rating, rating_description "
                "FROM show_ratings WHERE event_id=?",
                (ev_id,),
            ).fetchone()
            if sr_row:
                (fan_r, comm_r, exc_r, qual_r, ov_r, desc) = sr_row
                # P3.6 — FOTN / Best KO / Best Sub awards. These are
                # written by show_rating._award_card_bonuses as
                # finance_transactions rows with transaction_type=
                # 'bonus_payment' + a description like "Fight of the
                # Night (split with X)" / "Best Knockout of the Night"
                # / "Best Submission of the Night". Query them + map
                # to fighter names so the recap screen can show the
                # awards row alongside the show rating.
                awards = {"fotn": [], "best_ko": None, "best_sub": None}
                aw_rows = conn.execute(
                    "SELECT ft.fighter_id, ft.description, "
                    "f.first_name || ' ' || f.last_name "
                    "FROM finance_transactions ft "
                    "JOIN fighters f ON f.fighter_id=ft.fighter_id "
                    "WHERE ft.event_id=? "
                    "AND ft.transaction_type='bonus_payment'",
                    (ev_id,),
                ).fetchall()
                for (aw_fid, aw_desc, aw_name) in aw_rows:
                    d = (aw_desc or "").lower()
                    if "fight of the night" in d:
                        if aw_name not in awards["fotn"]:
                            awards["fotn"].append(aw_name)
                    elif "best knockout" in d:
                        awards["best_ko"] = aw_name
                    elif "best submission" in d:
                        awards["best_sub"] = aw_name
                show_rating = {
                    "fan_rating": fan_r, "commercial_rating": comm_r,
                    "excitement_rating": exc_r, "quality_rating": qual_r,
                    "overall_rating": ov_r,
                    "overall_rating_phrase": _rating_voice_phrase(
                        ov_r, "show"),
                    "rating_description": desc or "",
                    "awards": awards,
                }

            # "Next Fight" + "is last fight on card" detection.
            # P3.3 — "Next Fight" picks the next unresolved fight in
            # REVERSE card_slot order (prelims → featured_prelim →
            # co_main → main_event LAST). Previously this used
            # fight_id ASC, which (because confirm_card assigns
            # main_event at idx=0) played the main event first.
            next_unresolved_fight_id = None
            is_last_fight_on_card = False
            next_row = conn.execute(
                "SELECT fight_id FROM fights WHERE event_id=? "
                "AND winner_fighter_id IS NULL AND result_type IS NULL "
                "AND fight_id != ? "
                "ORDER BY CASE card_slot "
                "  WHEN 'opener' THEN 1 "
                "  WHEN 'prelim' THEN 2 "
                "  WHEN 'featured_prelim' THEN 3 "
                "  WHEN 'co_main' THEN 4 "
                "  WHEN 'main_event' THEN 5 "
                "  ELSE 6 END, fight_id ASC LIMIT 1",
                (ev_id, fid),
            ).fetchone()
            if next_row:
                next_unresolved_fight_id = next_row[0]
            else:
                # Is this the last unresolved fight on the card?
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM fights WHERE event_id=? "
                    "AND winner_fighter_id IS NULL AND result_type IS NULL",
                    (ev_id,),
                ).fetchone()[0]
                # If remaining == 0 AND this fight is resolved → it was the last.
                # If remaining == 1 AND this fight is unresolved → it's the last.
                if is_resolved:
                    is_last_fight_on_card = (remaining == 0)
                else:
                    is_last_fight_on_card = (remaining == 1)

            slot_labels = {
                "main_event": "MAIN EVENT",
                "co_main": "CO-MAIN EVENT",
                "featured_prelim": "FEATURED PRELIM",
                "prelim": "PRELIM",
                "opener": "OPENER",
            }

            return {
                "ok": True,
                "fight_id": fid,
                "event_id": ev_id,
                "is_resolved": is_resolved,
                "fight": {
                    "fight_id": fid,
                    "event_id": ev_id,
                    "scheduled_rounds": sched_rounds or 3,
                    "card_slot": card_slot or "prelim",
                    "card_slot_label": slot_labels.get(
                        card_slot, (card_slot or "PRELIM").upper()),
                    "is_title_fight": bool(is_title),
                    "weight_class_name": wc_name or "",
                },
                "event": {
                    "event_id": ev_id,
                    "event_name": event_name or "",
                    "event_date": event_date or "",
                    "promotion_name": promo_name or "",
                    "venue_name": venue_name or "",
                },
                "red": red_brief,
                "blue": blue_brief,
                "rivalry": rivalry,
                "previous_meetings": previous_meetings,
                "matchup_analysis": matchup_analysis,
                "beats": beats,
                "rounds": rounds,
                "highlights": highlights,
                "play_by_play": play_by_play,
                "extra_segments": extra_segments,
                "result": result,
                "show_rating": show_rating,
                "next_unresolved_fight_id": next_unresolved_fight_id,
                "is_last_fight_on_card": is_last_fight_on_card,
            }
        except Exception as e:
            print(f"[api.get_fight_night_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e)}

    def get_event_fights(self, event_id):
        """Return all fights on an event with their resolution status.

        Called by the Fight Night transport bar to display "Fight X
        of Y" + a card-progress strip. Resolved fights show the result
        label + finish round; unresolved fights show "SCHEDULED".

        Returns:
          {
            "ok": True|False,
            "event_id", "event_name", "event_date",
            "total_fights", "resolved_count",
            "fights": [
              {
                "fight_id", "card_slot", "card_slot_label",
                "card_position",  # 1-indexed position on the card
                "is_title_fight",
                "red": {"fighter_id", "name", "nickname"},
                "blue": {"fighter_id", "name", "nickname"},
                "is_resolved": bool,
                "winner_id", "result_type", "result_label",
                "finish_round", "finish_time"
              }
            ]
          }
        """
        try:
            eid = int(event_id)
            ev = self.conn.execute(
                "SELECT event_id, event_name, event_date FROM events "
                "WHERE event_id=?",
                (eid,),
            ).fetchone()
            if not ev:
                return {"ok": False, "error": "Event not found."}

            fights = self.conn.execute(
                "SELECT f.fight_id, f.card_slot, f.is_title_fight, "
                "f.winner_fighter_id, f.result_type, "
                "f.finish_round, f.finish_time, "
                "ec.card_position "
                "FROM fights f "
                "LEFT JOIN event_cards ec ON ec.fight_id=f.fight_id "
                "WHERE f.event_id=? "
                # P3.3 — prelims FIRST, main event LAST (the order the
                # fights actually play out on fight night). The
                # previous ordering (main_event=1) was display-only
                # and didn't match the playback order, which confused
                # the player ("why is the main event resolving first?").
                "ORDER BY CASE f.card_slot "
                "  WHEN 'opener' THEN 1 "
                "  WHEN 'prelim' THEN 2 "
                "  WHEN 'featured_prelim' THEN 3 "
                "  WHEN 'co_main' THEN 4 "
                "  WHEN 'main_event' THEN 5 "
                "  ELSE 6 END, f.fight_id ASC",
                (eid,),
            ).fetchall()

            fight_ids = [r[0] for r in fights]
            parts_by_fight = {}
            if fight_ids:
                placeholders = ",".join("?" * len(fight_ids))
                part_rows = self.conn.execute(
                    "SELECT fp.fight_id, fp.fighter_id, fp.corner, "
                    "f.first_name, f.last_name, f.nickname "
                    "FROM fight_participants fp "
                    "JOIN fighters f ON f.fighter_id=fp.fighter_id "
                    f"WHERE fp.fight_id IN ({placeholders})",
                    tuple(fight_ids),
                ).fetchall()
                for (pfid, pfidf, pcorner, fn, ln, nick) in part_rows:
                    parts_by_fight.setdefault(pfid, {})[pcorner] = {
                        "fighter_id": pfidf,
                        "name": f"{fn or ''} {ln or ''}".strip(),
                        "nickname": nick or "",
                    }

            slot_labels = {
                "main_event": "MAIN EVENT",
                "co_main": "CO-MAIN EVENT",
                "featured_prelim": "FEATURED PRELIM",
                "prelim": "PRELIM",
                "opener": "OPENER",
            }

            out_fights = []
            resolved_count = 0
            for i, r in enumerate(fights):
                (fid, slot, is_title, wid, rtype, frnd, ftime,
                 card_pos) = r
                parts = parts_by_fight.get(fid, {})
                red = parts.get("red")
                blue = parts.get("blue")
                is_resolved = (wid is not None) or (rtype is not None)
                if is_resolved:
                    resolved_count += 1
                out_fights.append({
                    "fight_id": fid,
                    "card_slot": slot or "prelim",
                    "card_slot_label": slot_labels.get(
                        slot, (slot or "prelim").upper()),
                    "card_position": card_pos or (i + 1),
                    "is_title_fight": bool(is_title),
                    "red": red,
                    "blue": blue,
                    "is_resolved": is_resolved,
                    "winner_id": wid,
                    "result_type": rtype or "",
                    "result_label": _result_type_label(rtype),
                    "finish_round": frnd,
                    "finish_time": ftime or "",
                })

            return {
                "ok": True,
                "event_id": ev[0],
                "event_name": ev[1] or "",
                "event_date": ev[2] or "",
                "total_fights": len(out_fights),
                "resolved_count": resolved_count,
                "fights": out_fights,
            }
        except Exception as e:
            print(f"[api.get_event_fights] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e), "fights": []}

    def _portrait_data_uri(self, fighter_id):
        """Return a data URI for the fighter's portrait, or '' if none.

        Thin wrapper around get_fighter_portrait_b64 that returns a
        ready-to-use <img src="..."> value. Avoids the extra Python
        call from JS when bundling portraits into the Fight Night data
        payload.
        """
        try:
            p = self.get_fighter_portrait_b64(fighter_id)
            if not p or not p.get("has_portrait"):
                return ""
            return p.get("data_uri", "")
        except Exception:
            return ""

    # ============================================================
    # THE RANKINGS — divisional top 15 (INFO-SCREENS-BATCH-1 §3)
    # ============================================================
    #
    # Per docs/SCREEN_DATA_AUDIT.md §2.5 + §5.5: rankings table is
    # per (fighter_id, weight_class_id, promotion_id). The Rankings
    # screen shows the player's promo's divisional top 15 — the
    # matchmaking context the player needs to pick opponents.
    #
    # Per CONVENTIONS §14: NEVER show rankings.rating (raw ELO float)
    # — show rank position (#1, #2, …) only. The momentum phrase
    # from fighter_descriptors is the voice for "is this fighter
    # climbing or falling". Rank change is derived from the last
    # fight outcome (W → ▲, L → ▼, no fight → →) since the engine
    # doesn't store a rank-history table.

    def get_rankings_data(self, weight_class_id=None, gender=None,
                          promo_filter=None):
        """Return the top-15 rankings for a specific weight class.

        Args:
          weight_class_id: int (defaults to first male WC if None)
          gender:          "male"|"female"|None (used only when
                           weight_class_id is None — picks the first
                           WC of that gender)
          promo_filter:    "mine"|"all"|None (P4.4)
                           - "mine" (default): only the player's
                             promo's rankings rows for this WC
                             (existing behavior, backwards-compatible).
                           - "all": pool all promotions' rankings rows
                             for this WC, top 15 by ELO. The
                             "contracted_to" column then matters
                             (shows where each fighter is signed).

        Returns:
          {
            "weight_class_id", "weight_class_name", "gender",
            "weight_classes": [
              {"weight_class_id", "name", "gender", "display_order"}
            ],  # all WCs for the filter dropdown (grouped by gender)
            "player_promo_id", "player_promo_name",
            "promo_filter": "mine"|"all",   # P4.4
            "champion": {  # current champ for this WC + player's promo, or null
              "fighter_id", "name", "nickname", "champion_since_date",
              "title_defenses_count", "title_reigns_count", "reign_length"
            } | null,
            "rankings": [
              {
                "rank",  # 1-15 (P4.2: sequential, no ties —
                         # ORDER BY rating DESC, fighter_id ASC)
                "fighter_id", "name", "nickname",
                "record_display",  # "11-3-0"
                "win_streak", "loss_streak", "streak_display",  # "3W"|"2L"|""
                "momentum_label", "momentum_phrase",  # from fighter_descriptors
                "career_phase_short",  # italic stage phrase
                "last_fight_outcome",  # "win"|"loss"|"draw"|"nc"|null
                "rank_change",         # "up"|"down"|"flat"|"new"
                "rank_change_symbol",  # "▲"|"▼"|"→"|"●"
                "rank_change_phrase",  # "rising"|"falling"|"steady"|"new entrant"
                "is_champion",         # bool (matches champion.fighter_id)
                "last_fight_date", "fights_count",
                "contracted_to",       # P4.4 — promo name the fighter
                                       # is currently signed to (from
                                       # fighters.current_promotion_id)
                "is_player_promo_fighter"  # P4.4 — bool, True when the
                                       # fighter's contracted promo is
                                       # the player's promo (used by
                                       # rankings.js to highlight).
              }
            ]
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn

            # P4.4 — normalize promo_filter. Default "mine" (backwards-
            # compatible with existing callers that don't pass it).
            pf = (promo_filter or "mine").lower()
            if pf not in ("mine", "all"):
                pf = "mine"

            # All weight classes for the dropdown (grouped by gender).
            wc_rows = conn.execute(
                "SELECT weight_class_id, name, gender, display_order "
                "FROM weight_classes ORDER BY display_order, weight_class_id"
            ).fetchall()
            weight_classes = [
                {"weight_class_id": r[0], "name": r[1],
                 "gender": r[2], "display_order": r[3]}
                for r in wc_rows
            ]

            # Resolve the target weight_class_id.
            wc_id = None
            if weight_class_id:
                try:
                    wc_id = int(weight_class_id)
                except (TypeError, ValueError):
                    wc_id = None
            if wc_id is None:
                # Default to first WC of the requested gender (or male).
                target_gender = (gender or "male").lower()
                for wc in weight_classes:
                    if wc["gender"] == target_gender:
                        wc_id = wc["weight_class_id"]
                        break
                if wc_id is None and weight_classes:
                    wc_id = weight_classes[0]["weight_class_id"]
            if wc_id is None:
                return {"ok": False, "error": "No weight classes found.",
                        "weight_classes": weight_classes,
                        "rankings": [], "champion": None,
                        "promo_filter": pf}

            # WC + promo info.
            wc_row = conn.execute(
                "SELECT name, gender FROM weight_classes WHERE weight_class_id=?",
                (wc_id,),
            ).fetchone()
            wc_name = wc_row[0] if wc_row else "—"
            wc_gender = wc_row[1] if wc_row else "male"

            p_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?", (pid,)).fetchone()
            promo_name = p_row[0] if p_row else "Your Promotion"

            # Current champion for this WC + player's promo. (Still
            # scoped to the player's promo — the player's title is the
            # one they care about; "all" mode just widens the rankings
            # pool, not the title.)
            champ_row = conn.execute(
                "SELECT t.current_champion_fighter_id, t.champion_since_date, "
                "t.title_defenses_count, t.title_reigns_count, t.is_vacant, "
                "f.first_name, f.last_name, f.nickname "
                "FROM titles t "
                "LEFT JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id "
                "WHERE t.promotion_id=? AND t.weight_class_id=?",
                (pid, wc_id),
            ).fetchone()
            champion = None
            champ_fighter_id = None
            if champ_row and champ_row[0] and not champ_row[4]:
                champ_fighter_id = champ_row[0]
                # Sim date for reign length.
                clock = get_clock(conn)
                sim_date_str = clock[0] if clock else None
                reign_len = _reign_length(champ_row[1], sim_date_str)
                champion = {
                    "fighter_id": champ_fighter_id,
                    "name": f"{champ_row[5] or ''} {champ_row[6] or ''}".strip(),
                    "nickname": champ_row[7] or "",
                    "champion_since_date": champ_row[1] or "",
                    "title_defenses_count": int(champ_row[2] or 0),
                    "title_reigns_count": int(champ_row[3] or 0),
                    "reign_length": reign_len,
                }

            # Top 15 ranked fighters for this WC, by rating DESC then
            # fighter_id ASC (P4.2 — tiebreaker so no two fighters
            # share a rank). When promo_filter='mine', scope to the
            # player's promo (existing behavior). When 'all', pool all
            # promotions.
            if pf == "all":
                promo_clause = ""
                query_params = (wc_id,)
            else:
                promo_clause = "AND r.promotion_id=? "
                query_params = (wc_id, pid)
            r_rows = conn.execute(
                "SELECT r.fighter_id, r.rating, r.fights_count, r.wins, "
                "r.losses, r.draws, r.last_fight_date, "
                "f.first_name, f.last_name, f.nickname, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "fc.win_streak, fc.loss_streak, "
                "fd.momentum, fd.momentum_short, fd.career_phase_short, "
                # P4.4 — contracted_to (fighters.current_promotion_id
                # → promotions.name). May differ from r.promotion_id
                # (ranked-promo) when a fighter has been signed by a
                # different promo since the rankings row was last
                # recomputed.
                "f.current_promotion_id, p.name AS contracted_to_name, "
                # Phase 6 / Task C2 — last_outcome via a JOINED
                # subquery (was: correlated subquery per row → 15
                # subqueries). We pre-compute each fighter's MAX
                # fight_history_id in a derived table, then JOIN back
                # to fight_history once for the outcome on that row.
                "last_fh.outcome AS last_outcome "
                "FROM rankings r "
                "JOIN fighters f ON f.fighter_id=r.fighter_id "
                "LEFT JOIN promotions p ON p.promotion_id=f.current_promotion_id "
                "LEFT JOIN fighter_career fc ON fc.fighter_id=r.fighter_id "
                "LEFT JOIN fighter_descriptors fd ON fd.fighter_id=r.fighter_id "
                "LEFT JOIN ("
                "  SELECT fh.fighter_id, fh.outcome "
                "  FROM fight_history fh "
                "  JOIN (SELECT fighter_id, MAX(fight_history_id) AS max_fh_id "
                "        FROM fight_history GROUP BY fighter_id) latest "
                "    ON latest.max_fh_id = fh.fight_history_id"
                ") last_fh ON last_fh.fighter_id = r.fighter_id "
                "WHERE r.weight_class_id=? " + promo_clause +
                "ORDER BY r.rating DESC, r.fighter_id ASC LIMIT 15",
                query_params,
            ).fetchall()

            rankings = []
            for idx, r in enumerate(r_rows):
                # P4.2 — sequential rank 1..N (no ties). The ORDER BY
                # clause above already breaks rating ties by fighter_id.
                rank = idx + 1
                (fid, rating, fights_count, wins, losses, draws, last_date,
                 fn, ln, nick, cwins, closses, cdraws, ws, ls,
                 mom_long, mom_short, phase_short,
                 contracted_pid, contracted_to_name, last_outcome) = r
                # Decode momentum_short: 'label||phrase'.
                mom_label = ""
                mom_phrase = ""
                if mom_short:
                    parts = mom_short.split("||", 1)
                    if len(parts) == 2:
                        mom_label = parts[0]
                        mom_phrase = parts[1]
                    else:
                        mom_phrase = mom_short
                elif mom_long:
                    parts = mom_long.split("||", 1)
                    if len(parts) == 2:
                        mom_label = parts[0]
                        mom_phrase = parts[1]
                    else:
                        mom_phrase = mom_long
                # Streak display.
                streak_str = ""
                if ws and int(ws) >= 2:
                    streak_str = f"{ws}W"
                elif ls and int(ls) >= 2:
                    streak_str = f"{ls}L"
                # Rank change derived from last fight outcome.
                # ▲ win, ▼ loss, → draw/nc/no fight.
                if last_outcome == "win":
                    rank_change = "up"
                    rank_change_symbol = "▲"
                    rank_change_phrase = "rising"
                elif last_outcome == "loss":
                    rank_change = "down"
                    rank_change_symbol = "▼"
                    rank_change_phrase = "falling"
                elif last_outcome in ("draw", "nc"):
                    rank_change = "flat"
                    rank_change_symbol = "→"
                    rank_change_phrase = "steady"
                else:
                    rank_change = "new"
                    rank_change_symbol = "●"
                    rank_change_phrase = "new entrant"

                record_w = int(cwins or wins or 0)
                record_l = int(closses or losses or 0)
                record_d = int(cdraws or draws or 0)

                rankings.append({
                    "rank": rank,
                    "fighter_id": fid,
                    "name": f"{fn or ''} {ln or ''}".strip(),
                    "nickname": nick or "",
                    "record_display": f"{record_w}-{record_l}-{record_d}",
                    "win_streak": int(ws or 0),
                    "loss_streak": int(ls or 0),
                    "streak_display": streak_str,
                    "momentum_label": mom_label,
                    "momentum_phrase": mom_phrase,
                    "career_phase_short": (phase_short.split("||", 1)[-1]
                                            if phase_short else ""),
                    "last_fight_outcome": last_outcome,
                    "rank_change": rank_change,
                    "rank_change_symbol": rank_change_symbol,
                    "rank_change_phrase": rank_change_phrase,
                    "is_champion": (champ_fighter_id == fid),
                    "last_fight_date": last_date or "",
                    "fights_count": int(fights_count or 0),
                    # P4.4 — contracted_to: the promo the fighter is
                    # currently signed to (not necessarily the promo
                    # they're ranked in).
                    "contracted_to": contracted_to_name or "—",
                    "is_player_promo_fighter": (contracted_pid == pid),
                })

            return {
                "weight_class_id": wc_id,
                "weight_class_name": wc_name,
                "gender": wc_gender,
                "weight_classes": weight_classes,
                "player_promo_id": pid,
                "player_promo_name": promo_name,
                "promo_filter": pf,   # P4.4
                "champion": champion,
                "rankings": rankings,
            }
        except Exception as e:
            print(f"[api.get_rankings_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e), "rankings": [],
                    "weight_classes": [], "champion": None,
                    "promo_filter": (promo_filter or "mine").lower()}

    # ============================================================
    # BELTS — title grid (INFO-SCREENS-BATCH-1 §4)
    # ============================================================
    #
    # Per docs/SCREEN_DATA_AUDIT.md §1.2: titles table has 12 rows
    # per promo (one per weight class), with is_vacant flag +
    # current_champion_fighter_id + champion_since_date + reigns
    # + defenses counts. The Belts screen surfaces ALL titles
    # across ALL promos so the player can see who holds the gold
    # elsewhere (Discovery reward + Kingmaker fantasy — "I want
    # that belt too").
    #
    # Voice compliance (CONVENTIONS §14):
    #   - Reign length as voice phrase ("just won the belt" /
    #     "long-reigning champion" / "era-defining reign").
    #   - Player's promo's titles get a gold border highlight.
    #   - No raw fighter attribute numbers — only name + reign
    #     metadata.

    @staticmethod
    def _reign_voice_phrase(reign_months):
        """Voice phrase for a champion's reign length.

        Returns a short phrase (LONG variant — used as card
        subtitle). reign_months is int months since champion_since_date.
        """
        try:
            m = int(reign_months or 0)
        except (TypeError, ValueError):
            m = 0
        if m < 0:
            return "reign data lost"
        if m == 0:
            return "just won the belt"
        if m < 3:
            return "early in their reign"
        if m < 6:
            return "settling in as champion"
        if m < 12:
            return f"reigning for {m} months"
        years = m // 12
        rem_months = m % 12
        if years == 1 and rem_months == 0:
            return "a year into the reign"
        if years == 1:
            return f"reigning for 1 year{(' ' + str(rem_months) + ' months') if rem_months else ''}"
        if years < 3:
            return f"reigning for {years} years"
        if years < 5:
            return "long-reigning champion"
        return "era-defining reign"

    def get_titles_data(self):
        """Return all titles across all promos, grouped by promo.

        Returns:
          {
            "player_promo_id", "player_promo_name",
            "promos": [
              {
                "promo_id", "promo_name", "logo_b64",
                "is_player_promo": bool,
                "titles": [
                  {
                    "title_id", "weight_class_id", "weight_class_name",
                    "weight_class_gender", "is_vacant",
                    "champion": {
                      "fighter_id", "name", "nickname",
                      "champion_since_date", "reign_length",
                      "reign_months", "reign_voice",
                      "title_defenses_count", "title_reigns_count",
                      "portrait_b64"
                    } | null
                  }
                ]
              }
            ]
          }
        """
        try:
            pid = self.get_player_promotion()
            conn = self.conn

            # Sim date for reign length.
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            try:
                sim_dt = datetime.strptime(sim_date_str, "%Y-%m-%d") if sim_date_str else None
            except (ValueError, TypeError):
                sim_dt = None

            # Fetch all titles joined to WC + champion fighter + promo.
            rows = conn.execute(
                "SELECT t.title_id, t.promotion_id, t.weight_class_id, "
                "t.current_champion_fighter_id, t.champion_since_date, "
                "t.title_reigns_count, t.title_defenses_count, t.is_vacant, "
                "wc.name, wc.gender, wc.display_order, "
                "p.name, "
                "f.first_name, f.last_name, f.nickname, f.portrait_path "
                "FROM titles t "
                "JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id "
                "JOIN promotions p ON p.promotion_id=t.promotion_id "
                "LEFT JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id "
                "ORDER BY p.promotion_id ASC, wc.display_order ASC, wc.weight_class_id ASC"
            ).fetchall()

            # Group by promo (preserve first-seen order).
            promos_by_id = {}
            promo_order = []
            for r in rows:
                (tid, p_id, wc_id, champ_fid, since_date, reigns, defs,
                 is_vacant, wc_name, wc_gender, wc_order, p_name,
                 fn, ln, nick, portrait_path) = r

                champion = None
                if champ_fid and not is_vacant:
                    reign_len = _reign_length(since_date, sim_date_str)
                    # Compute months for voice phrase.
                    reign_months = 0
                    try:
                        since_dt = datetime.strptime(since_date, "%Y-%m-%d")
                        if sim_dt:
                            reign_months = (sim_dt.year - since_dt.year) * 12 + \
                                           (sim_dt.month - since_dt.month)
                            if sim_dt.day < since_dt.day:
                                reign_months -= 1
                    except (TypeError, ValueError):
                        reign_months = 0
                    champion = {
                        "fighter_id": champ_fid,
                        "name": f"{fn or ''} {ln or ''}".strip(),
                        "nickname": nick or "",
                        "champion_since_date": since_date or "",
                        "reign_length": reign_len,
                        "reign_months": reign_months,
                        "reign_voice": self._reign_voice_phrase(reign_months),
                        "title_defenses_count": int(defs or 0),
                        "title_reigns_count": int(reigns or 0),
                        "portrait_b64": None,  # populated below (lazy)
                    }

                title_obj = {
                    "title_id": tid,
                    "weight_class_id": wc_id,
                    "weight_class_name": wc_name or "",
                    "weight_class_gender": wc_gender or "male",
                    "is_vacant": bool(is_vacant),
                    "champion": champion,
                }

                if p_id not in promos_by_id:
                    promos_by_id[p_id] = {
                        "promo_id": p_id,
                        "promo_name": p_name or "",
                        "logo_b64": _load_logo_b64(p_id),
                        "is_player_promo": (p_id == pid),
                        "titles": [],
                    }
                    promo_order.append(p_id)
                promos_by_id[p_id]["titles"].append(title_obj)

            promos_list = [promos_by_id[pid_] for pid_ in promo_order]

            # Lazy-load portraits only for held titles (avoid 100+
            # disk reads for vacant titles). Reuses the cached
            # get_fighter_portrait_b64 method which already handles
            # missing files + corrupted uploads gracefully.
            for promo in promos_list:
                for title in promo["titles"]:
                    champ = title.get("champion")
                    if not champ:
                        continue
                    fid = champ["fighter_id"]
                    try:
                        portrait_data = self.get_fighter_portrait_b64(fid)
                        if portrait_data and portrait_data.get("has_portrait"):
                            champ["portrait_b64"] = portrait_data.get("data_uri")
                        else:
                            champ["portrait_b64"] = None
                    except Exception:
                        champ["portrait_b64"] = None

            # Player promo name for the header.
            p_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?",
                (pid,) if pid else (0,),
            ).fetchone() if pid else None
            player_promo_name = p_row[0] if p_row else "Your Promotion"

            return {
                "player_promo_id": pid,
                "player_promo_name": player_promo_name,
                "promos": promos_list,
            }
        except Exception as e:
            print(f"[api.get_titles_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e), "promos": []}

    # ============================================================
    # P1-WIRE-4-SCREENS — Training Camps (Gyms) screen
    # ============================================================
    # Per docs/P1_PLAN_WIRE_SCREENS.md §4 + docs/REVIEW_P1_SCREEN_BACKENDS.md
    # §4: paginated gyms + active camps. Backed by src/services/
    # training_svc.py + src/tick_processor.py (~840 LOC of camp
    # progression + completion logic) + src/services/matchmaking.py
    # (camp creation on fight scheduling). 300 gyms / 138 active camps
    # in the DB. This method is purely a reader.
    # ------------------------------------------------------------

    def get_gyms_data(self, page=1, filters=None):
        """Return paginated gyms for the Gym Directory tab.

        Args:
          page:    int page number (20 gyms per page)
          filters: {
            "culture_tone": "all" | "predator" | "loose" |
                            "disciplined" | "balanced",
            "sort":         "reputation_desc" (default) |
                            "facility_desc" | "dev_focus_desc" |
                            "fighter_count_desc",
            "search":       substring on gym name
          }

        Returns:
          {
            "gyms": [
              {
                "gym_id", "name", "city", "nation",
                "reputation", "facility_quality", "medical_support",
                "sparring_depth", "development_focus",
                "weight_cut_support", "culture_tone",
                "culture_tone_label", "membership_cost",
                "membership_cost_display", "fighter_count",
                "active_camps_count", "quality_phrase"
              }, ...
            ],
            "total_gyms", "by_culture_tone": [{tone, label, count, avg_rep}],
            "page", "per_page": 20, "total", "total_pages", "filters"
          }
        """
        try:
            conn = self.conn
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 20

            culture = (filters.get("culture_tone") or "").strip()
            sort = (filters.get("sort") or "reputation_desc").strip()
            search = (filters.get("search") or "").strip()

            where_parts = []
            params = []
            if culture and culture != "all":
                where_parts.append("g.culture_tone = ?")
                params.append(culture)
            if search:
                where_parts.append("g.name LIKE ?")
                params.append(f"%{search}%")
            where_sql = (" WHERE " + " AND ".join(where_parts)) \
                if where_parts else ""

            # Whitelist sort options → ORDER BY clause.
            sort_map = {
                "reputation_desc":      "g.reputation DESC, g.name",
                "facility_desc":        "g.facility_quality DESC, g.name",
                "dev_focus_desc":       "g.development_focus DESC, g.name",
                "fighter_count_desc":   "fc DESC, g.reputation DESC, g.name",
            }
            order_sql = sort_map.get(sort, sort_map["reputation_desc"])

            # Total count.
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM gyms g{where_sql}", params
            ).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page

            # Page rows — LEFT JOIN fighter count subquery (cheap; the
            # fighters.current_gym_id index exists from the seed).
            #
            # Phase 6 / Task B4 — LEFT JOIN gym_descriptors (the cache
            # table populated by Task A1's gym_identity_engine; 329 rows).
            # The `gyms` table itself is still a simulation table whose
            # raw 0-100 ints (reputation/facility_quality/medical/…)
            # are kept in the response for bar-fill widths (per §17.4
            # carve-out), but the JS layer should display the voice
            # phrases from gym_descriptors instead of the raw ints.
            rows_sql = (
                "SELECT g.gym_id, g.name, "
                "  g.reputation, g.facility_quality, g.medical_support, "
                "  g.sparring_depth, g.development_focus, "
                "  g.weight_cut_support, g.culture_tone, "
                "  g.membership_cost, "
                "  c.name, n.name, "
                "  gd.identity_label, gd.known_for, gd.produces, "
                "  gd.weakness, gd.development_rating_desc, "
                "  (SELECT COUNT(*) FROM fighters f "
                "   WHERE f.current_gym_id = g.gym_id "
                "   AND f.is_active = 1) AS fc, "
                "  (SELECT COUNT(*) FROM training_camps tc "
                "   WHERE tc.gym_id = g.gym_id "
                "   AND tc.is_active = 1) AS ac "
                "FROM gyms g "
                "LEFT JOIN cities c ON c.city_id = g.city_id "
                "LEFT JOIN nations n ON n.nation_id = g.nation_id "
                "LEFT JOIN gym_descriptors gd ON gd.gym_id = g.gym_id "
                + where_sql +
                " ORDER BY " + order_sql +
                " LIMIT ? OFFSET ?"
            )
            rows = conn.execute(rows_sql, params + [per_page, offset]).fetchall()

            gyms = []
            for r in rows:
                (gid, gname, rep, fac, med, spar, dev, wc_sup, tone,
                 cost, cname, nname,
                 identity_label, known_for, produces, weakness,
                 development_rating_desc,
                 fc, ac) = r
                # Voice phrase for overall quality (per brief).
                quality_phrase = _gym_quality_phrase(fac)
                gyms.append({
                    "gym_id": gid,
                    "name": gname or "",
                    "city": cname or "",
                    "nation": nname or "",
                    # Phase 6 / Task B4 — raw 0-100 ints are KEPT in
                    # the response for bar-fill widths (§17.4 carve-out)
                    # but the JS layer should NOT display them as text.
                    # The matching voice phrases from gym_descriptors
                    # are exposed below (identity_label, known_for,
                    # produces, weakness, development_rating_desc).
                    "reputation": int(rep or 0),
                    "facility_quality": int(fac or 0),
                    "medical_support": int(med or 0),
                    "sparring_depth": int(spar or 0),
                    "development_focus": int(dev or 0),
                    "weight_cut_support": int(wc_sup or 0),
                    "culture_tone": tone or "balanced",
                    "culture_tone_label": _gym_culture_label(tone),
                    "membership_cost": float(cost or 0),
                    "membership_cost_display": _format_cash(float(cost or 0)) + "/mo",
                    "fighter_count": int(fc or 0),
                    "active_camps_count": int(ac or 0),
                    "quality_phrase": quality_phrase,
                    # Phase 6 / Task B4 — voice phrases from the
                    # gym_descriptors cache table (§17.1). These
                    # REPLACE the raw 0-100 ints as the player-facing
                    # display values in gyms.js.
                    "identity_label": identity_label or "",
                    "known_for": known_for or "",
                    "produces": produces or "",
                    "weakness": weakness or "",
                    "development_rating_desc": (development_rating_desc
                                                or quality_phrase),
                })

            # Culture-tone breakdown — for the filter dropdown counts.
            tone_rows = conn.execute(
                "SELECT culture_tone, COUNT(*), ROUND(AVG(reputation),1) "
                "FROM gyms GROUP BY culture_tone ORDER BY 2 DESC"
            ).fetchall()
            by_culture_tone = [
                {"tone": t or "balanced",
                 "label": _gym_culture_label(t),
                 "count": int(c or 0),
                 "avg_rep": float(r or 0)}
                for (t, c, r) in tone_rows
            ]

            return {
                "gyms": gyms,
                "total_gyms": total,
                "by_culture_tone": by_culture_tone,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "filters": {
                    "culture_tone": culture or "all",
                    "sort": sort,
                    "search": search,
                },
            }
        except Exception as e:
            print(f"[api.get_gyms_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"gyms": [], "total_gyms": 0, "by_culture_tone": [],
                    "page": 1, "per_page": 20, "total": 0,
                    "total_pages": 1, "filters": {}, "error": str(e)}

    def get_training_camps_data(self, page=1, filters=None):
        """Return paginated training camps for the Active Camps tab.

        Phase 7 / Task A4 — §17.1 cache-table decision (NO-OP):

          ``training_camps`` is listed as a SIMULATION table in
          CONVENTIONS §17.3 (alongside `events`, `fights`, etc.).
          Per §17.1, Office Mode UI screens MUST read from
          `*_descriptors` cache tables only — direct reads of
          simulation tables are a §14-class violation.

          HOWEVER, training camps are short-lived operational
          state, not fighter identity:

            * A camp starts, trains for ~7-14 sim days, then ends
              (``is_active`` → ``is_completed``).
            * During the camp, ``camp_morale`` / ``camp_fatigue`` /
              ``camp_injury_risk`` fluctuate per tick.
            * When the camp ends, ``attribute_changes`` are applied
              to the fighter's ``fighter_attributes`` row (which IS
              then re-projected into ``fighter_descriptors`` via
              the interpretation layer's standard refresh).

          Building a ``training_camps_descriptors`` cache would be
          a net loss — the data is too volatile (per-tick state
          changes) and the projection would be stale before the
          player could read it. This is operationally analogous to
          the §17.2 Fight Night Exception: live operational data
          that updates between ticks is read directly.

          DECISION: NO CACHE — ``get_training_camps_data`` reads
          directly from ``training_camps`` (acceptable per the
          §17.2 carve-out spirit). The fighter-identity projection
          (career_phase, momentum, etc.) is still routed through
          ``fighter_descriptors`` via the standard interpretation
          pass — this carve-out applies ONLY to the camp-state
          fields (morale / fatigue / risk / days_remaining).

          Future-proofing: if a future audit demotes this carve-
          out, the fix would be to add a
          ``training_camps_descriptors`` table written by the
          existing daily interpretation pass (per-tick refresh
          is too costly). The UI contract (camp_morale /
          camp_fatigue / camp_injury_risk as 0-100 ints for bar
          widths) would not change.

        Args:
          page:    int page number (20 camps per page)
          filters: {
            "focus":  "all" | "striking" | "grappling" | "wrestling" |
                      "conditioning" | "submission" | "clinch" |
                      "general" | "weight_cut",
            "status": "active" (default) | "completed" | "all",
            "scope":  "all" (default) | "my_roster",
            "search": substring on fighter name
          }

        Returns:
          {
            "camps": [
              {
                "training_camp_id", "start_date", "end_date",
                "days_remaining", "camp_focus", "camp_focus_label",
                "camp_morale", "camp_fatigue", "camp_injury_risk",
                "is_active", "is_completed",
                "attribute_changes": {...}|null,  # JSON dict
                "camp_result_summary": str|null,
                "fighter": {id, name, nickname, promotion_id},
                "gym": {id, name},
                "event": {id, name, date}|null
              }, ...
            ],
            "active_count", "completed_count", "by_focus": [{...}],
            "page", "per_page": 20, "total", "total_pages", "filters"
          }
        """
        try:
            pid = self.get_player_promotion()
            conn = self.conn
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 20

            focus = (filters.get("focus") or "").strip()
            status = (filters.get("status") or "active").strip()
            scope = (filters.get("scope") or "all").strip()
            search = (filters.get("search") or "").strip()

            where_parts = []
            params = []
            if focus and focus != "all":
                where_parts.append("tc.camp_focus = ?")
                params.append(focus)
            if status == "active":
                where_parts.append("tc.is_active = 1")
            elif status == "completed":
                where_parts.append("tc.is_completed = 1")
            if scope == "my_roster" and pid:
                where_parts.append("f.current_promotion_id = ?")
                params.append(pid)
            if search:
                where_parts.append(
                    "(f.first_name LIKE ? OR f.last_name LIKE ? OR "
                    "(f.first_name || ' ' || f.last_name) LIKE ?)")
                like = f"%{search}%"
                params.extend([like, like, like])
            where_sql = (" WHERE " + " AND ".join(where_parts)) \
                if where_parts else ""

            # Total count.
            total = int(conn.execute(
                "SELECT COUNT(*) FROM training_camps tc "
                "LEFT JOIN fighters f ON f.fighter_id = tc.fighter_id "
                + where_sql,
                params
            ).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page

            # Current sim date for days_remaining.
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            try:
                sim_dt = datetime.strptime(sim_date_str, "%Y-%m-%d") \
                    if sim_date_str else None
            except (ValueError, TypeError):
                sim_dt = None

            rows_sql = (
                "SELECT tc.training_camp_id, tc.fighter_id, tc.gym_id, "
                "  tc.event_id, tc.start_date, tc.end_date, "
                "  tc.camp_focus, tc.camp_morale, tc.camp_fatigue, "
                "  tc.camp_injury_risk, tc.is_active, tc.is_completed, "
                "  tc.attribute_changes, tc.camp_result_summary, "
                "  f.first_name, f.last_name, f.nickname, "
                "  f.current_promotion_id, "
                "  g.name, "
                "  e.event_name, e.event_date "
                "FROM training_camps tc "
                "LEFT JOIN fighters f ON f.fighter_id = tc.fighter_id "
                "LEFT JOIN gyms g ON g.gym_id = tc.gym_id "
                "LEFT JOIN events e ON e.event_id = tc.event_id "
                + where_sql +
                " ORDER BY tc.start_date DESC, tc.training_camp_id DESC "
                "LIMIT ? OFFSET ?"
            )
            rows = conn.execute(rows_sql, params + [per_page, offset]).fetchall()

            camps = []
            for r in rows:
                (cid, fid, gid, eid, start_d, end_d, focus_v,
                 morale, fatigue, risk, is_active, is_completed,
                 attr_json, result_summary,
                 fn, ln, nick, f_promo, gname, ename, edate) = r
                # Parse attribute_changes JSON.
                attr_changes = None
                if attr_json:
                    try:
                        attr_changes = json.loads(attr_json)
                        if not isinstance(attr_changes, dict):
                            attr_changes = None
                    except Exception:
                        attr_changes = None
                # Compute days_remaining.
                days_remaining = None
                if end_d and sim_dt:
                    try:
                        end_dt = datetime.strptime(end_d, "%Y-%m-%d")
                        days_remaining = (end_dt - sim_dt).days
                    except (ValueError, TypeError):
                        pass
                camps.append({
                    "training_camp_id": cid,
                    "start_date": start_d or "",
                    "end_date": end_d or "",
                    "days_remaining": days_remaining,
                    "camp_focus": focus_v or "general",
                    "camp_focus_label": _camp_focus_label(focus_v),
                    "camp_morale": int(morale or 0),
                    "camp_fatigue": int(fatigue or 0),
                    "camp_injury_risk": int(risk or 0),
                    "is_active": bool(is_active),
                    "is_completed": bool(is_completed),
                    "attribute_changes": attr_changes,
                    "camp_result_summary": result_summary or "",
                    "fighter": {
                        "id": fid,
                        "name": f"{fn or ''} {ln or ''}".strip() or "—",
                        "nickname": nick or "",
                        "promotion_id": f_promo,
                    },
                    "gym": {"id": gid, "name": gname or ""},
                    "event": ({"id": eid, "name": ename, "date": edate or ""}
                              if (eid and ename) else None),
                })

            # Summary stats (always full-table).
            summary = conn.execute(
                "SELECT "
                "  SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END), "
                "  SUM(CASE WHEN is_completed=1 THEN 1 ELSE 0 END) "
                "FROM training_camps"
            ).fetchone()
            active_count = int(summary[0] or 0)
            completed_count = int(summary[1] or 0)

            # Breakdown by focus.
            focus_rows = conn.execute(
                "SELECT camp_focus, COUNT(*), "
                "  ROUND(AVG(camp_fatigue),1), ROUND(AVG(camp_morale),1) "
                "FROM training_camps GROUP BY camp_focus ORDER BY 2 DESC"
            ).fetchall()
            by_focus = [
                {"focus": f or "general",
                 "label": _camp_focus_label(f),
                 "count": int(c or 0),
                 "avg_fatigue": float(fat or 0),
                 "avg_morale": float(mor or 0)}
                for (f, c, fat, mor) in focus_rows
            ]

            return {
                "camps": camps,
                "active_count": active_count,
                "completed_count": completed_count,
                "by_focus": by_focus,
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "filters": {
                    "focus": focus or "all",
                    "status": status,
                    "scope": scope,
                    "search": search,
                },
            }
        except Exception as e:
            print(f"[api.get_training_camps_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"camps": [], "active_count": 0, "completed_count": 0,
                    "by_focus": [], "page": 1, "per_page": 20,
                    "total": 0, "total_pages": 1, "filters": {},
                    "error": str(e)}

    # ============================================================
    # P2-FINANCE-CONTRACTS — THE BOOKS (finance screen)
    # ============================================================
    #
    # Per docs/P2_PLAN_FINANCE_CONTRACTS.md §1:
    #   - Promo summary: current_cash, starting_budget, reputation
    #     (voice phrase), fan_trust (voice phrase).
    #   - Monthly burn rate: sum of expenses in last 30 days / 30 × 30
    #     (= daily burn × 30, projected forward as the "monthly burn").
    #   - Cash flow breakdown by type (last 30 days): revenue types vs
    #     expense types, each with amount + count + total + display.
    #   - Recent transactions: paginated 20/page, filterable by type
    #     + searchable by description.
    #   - Last event P&L: the most recent completed event for the
    #     player's promo that has finance_transactions, with revenue/
    #     expense breakdown + show rating voice phrase (if a show_ratings
    #     row exists).
    #
    # Voice compliance (CONVENTIONS §14):
    #   - Reputation + fan_trust → voice phrases ("Highly Respected" /
    #     "Strong"), NEVER raw 0-100 ints in headers.
    #   - Show rating → voice phrase ("instant classic" / "solid night"
    #     / "lackluster" via _archive_rating_phrase), NEVER raw int.
    #   - Cash amounts are OK as dollar figures (the player is the
    #     owner — they see their own money as numbers, not voice).
    #   - Monthly burn is OK as a dollar figure (it's a projection, not
    #     an attribute).

    # The canonical transaction_type categorization. Splits the 14
    # types into revenue (positive amount) vs expense (negative).
    # Used by both The Books (cash flow) and the filter dropdown.
    _FINANCE_REVENUE_TYPES = (
        "ticket_sales", "broadcast_revenue", "sponsorship",
        "merchandise", "concessions",
    )
    _FINANCE_EXPENSE_TYPES = (
        "fighter_purse", "staff_salary", "venue_rental",
        "marketing", "medical_cost", "bonus_payment",
        "signing_bonus", "weight_cut_penalty",
    )
    # show_quality_adjustment can swing either way — bucketed
    # dynamically by sign(amount) at query time.

    _FINANCE_TYPE_LABELS = {
        "ticket_sales":            "Ticket Sales",
        "broadcast_revenue":       "Broadcast Revenue",
        "sponsorship":             "Sponsorship",
        "merchandise":             "Merchandise",
        "concessions":             "Concessions",
        "fighter_purse":           "Fighter Purses",
        "staff_salary":            "Staff Salaries",
        "venue_rental":            "Venue Rental",
        "marketing":               "Marketing",
        "medical_cost":            "Medical Costs",
        "bonus_payment":           "Bonus Payments",
        "signing_bonus":           "Signing Bonuses",
        "weight_cut_penalty":      "Weight Cut Penalties",
        "show_quality_adjustment": "Show Quality Adjustments",
    }

    def _finance_type_label(self, t):
        return self._FINANCE_TYPE_LABELS.get(t or "", (t or "—").replace("_", " ").title())

    def _finance_type_is_revenue(self, t, amount):
        """Return True if this transaction_type+amount combo is revenue.

        show_quality_adjustment can be either — bucketed by sign.
        Others are statically bucketed by the type lists above.
        """
        if t == "show_quality_adjustment":
            try:
                return float(amount or 0) >= 0
            except (TypeError, ValueError):
                return True
        return (t or "") in self._FINANCE_REVENUE_TYPES

    def get_finance_data(self, page=1, filters=None):
        """Return the player's promotion finance summary + transactions.

        Args:
          page:    int page number, 1-indexed (20 transactions per page)
          filters: {
            "transaction_type": "all"|"ticket_sales"|...|None
            "search": str                        (substring match on description)
          }

        Returns:
          {
            "promo": {
              "promotion_id", "name", "current_cash", "starting_budget",
              "cash_display", "budget_display",
              "reputation_phrase", "fan_trust_phrase"
              # Phase 7 / Task A7 — raw reputation / fan_trust ints
              # DROPPED from the JSON (per §17.4 "Rich Not Thin").
              # The Finance screen's REPUTATION/FAN TRUST tiles use
              # the voice phrases only. If a future Finance UI wants
              # a bar fill, switch to _reputation_pct/_fan_trust_pct
              # (already defined near _reputation_phrase).
            },
            "monthly_burn": {
              "total_expenses_30d", "daily_burn_30d",
              "monthly_burn_estimated", "monthly_burn_display",
              "has_data"
            },
            "cash_flow_30d": {
              "revenue": [{"transaction_type", "label", "total", "count", "display"}],
              "expenses": [...],
              "revenue_total", "expense_total",
              "net_profit", "net_profit_display",
              "has_data"
            },
            "transactions": {
              "items": [{"transaction_id", "transaction_type", "type_label",
                         "amount", "amount_display", "is_revenue",
                         "description", "transaction_date",
                         "transaction_date_display",
                         "event_id", "fighter_id", "fighter_name"}],
              "page", "per_page": 20, "total", "total_pages",
              "filters": {"transaction_type", "search"}
            },
            "last_event_pl": {
              "event_id", "event_name", "event_date", "event_date_display",
              "revenue": [...], "expenses": [...],
              "revenue_total", "expense_total",
              "net_profit", "net_profit_display",
              "show_rating": {
                "rating_phrase", "rating_tier", "rating_color"
                # Phase 7 / Task A7 — raw overall_rating int DROPPED
                # (per §17.4). UI shows rating_phrase + rating_tier only.
              } | null
            } | null,
            "type_options": [{"value", "label", "is_revenue"}]
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            filters = filters or {}
            page = max(1, int(page or 1))
            per_page = 20

            # --- Promo summary ---
            promo_row = conn.execute(
                "SELECT promotion_id, name, current_cash, starting_budget, "
                "reputation, fan_trust FROM promotions WHERE promotion_id=?",
                (pid,),
            ).fetchone()
            if not promo_row:
                return {"ok": False, "error": "Promotion not found."}
            (_, p_name, current_cash, starting_budget, reputation,
             fan_trust) = promo_row
            current_cash = float(current_cash or 0)
            starting_budget = float(starting_budget or 0)
            reputation = int(reputation or 0)
            fan_trust = int(fan_trust or 0)

            # --- Sim date (for 30-day window + last-event P&L) ---
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            sim_date = None
            if sim_date_str:
                try:
                    sim_date = datetime.strptime(
                        str(sim_date_str)[:10], "%Y-%m-%d")
                except Exception:
                    sim_date = None
            # 30-day window cutoff (YYYY-MM-DD string for SQL comparison).
            date_30d_ago = None
            if sim_date:
                cutoff = sim_date - timedelta(days=30)
                date_30d_ago = cutoff.strftime("%Y-%m-%d")

            # --- Cash flow breakdown (last 30 days) ---
            cash_flow = {
                "revenue": [], "expenses": [],
                "revenue_total": 0.0, "expense_total": 0.0,
                "net_profit": 0.0, "net_profit_display": "$0",
                "has_data": False,
            }
            monthly_burn = {
                "total_expenses_30d": 0.0,
                "daily_burn_30d": 0.0,
                "monthly_burn_estimated": 0.0,
                "monthly_burn_display": "$0",
                "has_data": False,
            }
            if date_30d_ago:
                cf_rows = conn.execute(
                    "SELECT transaction_type, "
                    "       SUM(amount) AS total, COUNT(*) AS cnt "
                    "FROM finance_transactions "
                    "WHERE promotion_id=? AND transaction_date >= ? "
                    "GROUP BY transaction_type "
                    "ORDER BY SUM(ABS(amount)) DESC",
                    (pid, date_30d_ago),
                ).fetchall()
                revenue_total = 0.0
                expense_total = 0.0
                for r in cf_rows:
                    t_type, t_total, t_count = r
                    t_total = float(t_total or 0)
                    is_rev = self._finance_type_is_revenue(t_type, t_total)
                    entry = {
                        "transaction_type": t_type,
                        "label": self._finance_type_label(t_type),
                        "total": t_total,
                        "count": int(t_count or 0),
                        "display": _format_cash(t_total),
                        "is_revenue": is_rev,
                    }
                    if is_rev:
                        cash_flow["revenue"].append(entry)
                        revenue_total += t_total
                    else:
                        # expenses stored as negative — flip to positive
                        # for display in the Expenses column.
                        entry["total"] = abs(t_total)
                        entry["display"] = _format_cash(abs(t_total))
                        cash_flow["expenses"].append(entry)
                        expense_total += abs(t_total)
                cash_flow["revenue_total"] = revenue_total
                cash_flow["expense_total"] = expense_total
                net = revenue_total - expense_total
                cash_flow["net_profit"] = net
                cash_flow["net_profit_display"] = _format_cash(net)
                cash_flow["has_data"] = bool(cf_rows)

                # --- Monthly burn = (sum of 30d expenses / 30) × 30 ---
                # That's just the 30d expense total — but framed as a
                # projection ("at this rate, you'll burn $X next month").
                # Daily burn = total / 30, monthly burn = daily × 30.
                monthly_burn["total_expenses_30d"] = expense_total
                monthly_burn["daily_burn_30d"] = (
                    expense_total / 30.0 if expense_total else 0.0)
                monthly_burn["monthly_burn_estimated"] = expense_total
                monthly_burn["monthly_burn_display"] = _format_cash(
                    expense_total)
                monthly_burn["has_data"] = bool(expense_total)

            # --- Recent transactions (paginated + filterable) ---
            type_filter = (filters.get("transaction_type") or "all").lower()
            if type_filter == "":
                type_filter = "all"
            search = (filters.get("search") or "").strip()

            where_parts = ["promotion_id=?"]
            params = [pid]
            if type_filter != "all":
                where_parts.append("transaction_type=?")
                params.append(type_filter)
            if search:
                where_parts.append("(description LIKE ?)")
                params.append("%" + search + "%")
            where_sql = " AND ".join(where_parts)

            total = int(conn.execute(
                f"SELECT COUNT(*) FROM finance_transactions WHERE {where_sql}",
                params,
            ).fetchone()[0] or 0)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = min(page, total_pages)
            offset = (page - 1) * per_page

            tx_rows = conn.execute(
                f"SELECT transaction_id, transaction_type, amount, description, "
                f"      transaction_date, event_id, fighter_id "
                f"FROM finance_transactions "
                f"WHERE {where_sql} "
                f"ORDER BY transaction_date DESC, transaction_id DESC "
                f"LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            # Resolve fighter names in one pass (cache by id).
            fighter_ids = {r[6] for r in tx_rows if r[6]}
            fighter_names = {}
            if fighter_ids:
                fn_rows = conn.execute(
                    f"SELECT fighter_id, first_name, last_name, nickname "
                    f"FROM fighters WHERE fighter_id IN "
                    f"({','.join('?' * len(fighter_ids))})",
                    tuple(fighter_ids),
                ).fetchall()
                for fr in fn_rows:
                    fid, fn, ln, nick = fr
                    base = f"{fn or ''} {ln or ''}".strip()
                    if nick:
                        fighter_names[fid] = f"{base} '{nick}'"
                    else:
                        fighter_names[fid] = base

            tx_items = []
            for r in tx_rows:
                (tid, t_type, amount, desc, t_date, ev_id, fid) = r
                amount = float(amount or 0)
                is_rev = self._finance_type_is_revenue(t_type, amount)
                tx_items.append({
                    "transaction_id": tid,
                    "transaction_type": t_type,
                    "type_label": self._finance_type_label(t_type),
                    "amount": amount,
                    "amount_display": _format_cash(abs(amount)),
                    "is_revenue": is_rev,
                    "description": desc or "",
                    "transaction_date": t_date or "",
                    "transaction_date_display": (t_date or "")[:10],
                    "event_id": ev_id,
                    "fighter_id": fid,
                    "fighter_name": fighter_names.get(fid) if fid else None,
                })

            # --- Type options for the filter dropdown ---
            # Only types that actually appear for this promo (so the
            # dropdown isn't cluttered with 14 options when only 5 are
            # in use). Sorted: revenue first, then expenses, then "all".
            present_types = conn.execute(
                "SELECT DISTINCT transaction_type FROM finance_transactions "
                "WHERE promotion_id=? ORDER BY transaction_type",
                (pid,),
            ).fetchall()
            type_options = [{"value": "all", "label": "All Types",
                             "is_revenue": None}]
            for pt in present_types:
                t = pt[0]
                type_options.append({
                    "value": t,
                    "label": self._finance_type_label(t),
                    "is_revenue": self._finance_type_is_revenue(t, 0),
                })

            # --- Last event P&L ---
            # Find the most recent completed event for the player's promo
            # that has at least one finance_transaction row.
            last_event = None
            ev_row = conn.execute(
                "SELECT e.event_id, e.event_name, e.event_date "
                "FROM events e "
                "WHERE e.promotion_id=? AND e.status='completed' "
                "AND EXISTS (SELECT 1 FROM finance_transactions ft "
                "            WHERE ft.event_id=e.event_id) "
                "ORDER BY e.event_date DESC LIMIT 1",
                (pid,),
            ).fetchone()
            if ev_row:
                ev_id, ev_name, ev_date = ev_row
                ev_tx_rows = conn.execute(
                    "SELECT transaction_type, "
                    "       SUM(amount) AS total, COUNT(*) AS cnt "
                    "FROM finance_transactions "
                    "WHERE event_id=? "
                    "GROUP BY transaction_type "
                    "ORDER BY SUM(ABS(amount)) DESC",
                    (ev_id,),
                ).fetchall()
                ev_revenue = []
                ev_expenses = []
                ev_rev_total = 0.0
                ev_exp_total = 0.0
                for r in ev_tx_rows:
                    t_type, t_total, t_count = r
                    t_total = float(t_total or 0)
                    is_rev = self._finance_type_is_revenue(t_type, t_total)
                    entry = {
                        "transaction_type": t_type,
                        "label": self._finance_type_label(t_type),
                        "total": t_total,
                        "count": int(t_count or 0),
                        "display": _format_cash(abs(t_total)),
                        "is_revenue": is_rev,
                    }
                    if is_rev:
                        ev_revenue.append(entry)
                        ev_rev_total += t_total
                    else:
                        entry["total"] = abs(t_total)
                        ev_expenses.append(entry)
                        ev_exp_total += abs(t_total)
                ev_net = ev_rev_total - ev_exp_total
                # Show rating (if a show_ratings row exists).
                show_rating = None
                sr_row = conn.execute(
                    "SELECT overall_rating, rating_description "
                    "FROM show_ratings WHERE event_id=?",
                    (ev_id,),
                ).fetchone()
                if sr_row:
                    sr_overall, sr_desc = sr_row
                    phrase, tier, color = self._archive_rating_phrase(
                        int(sr_overall) if sr_overall is not None else None)
                    show_rating = {
                        # Phase 7 / Task A7 — raw overall_rating int
                        # DROPPED from the JSON (per §17.4 "Rich Not
                        # Thin"). The finance UI shows rating_phrase +
                        # rating_tier + rating_color (all voice/visual).
                        # `sr_overall` is still consumed server-side to
                        # pick the phrase/tier/color — it just doesn't
                        # cross the API boundary as a raw int.
                        "rating_phrase": phrase,
                        "rating_tier": tier,
                        "rating_color": color,
                        "rating_description": sr_desc or "",
                    }
                last_event = {
                    "event_id": ev_id,
                    "event_name": ev_name or "Untitled Card",
                    "event_date": ev_date or "",
                    "event_date_display": _format_long_date(ev_date),
                    "revenue": ev_revenue,
                    "expenses": ev_expenses,
                    "revenue_total": ev_rev_total,
                    "expense_total": ev_exp_total,
                    "net_profit": ev_net,
                    "net_profit_display": _format_cash(ev_net),
                    "show_rating": show_rating,
                }

            return {
                "promo": {
                    "promotion_id": pid,
                    "name": p_name,
                    "current_cash": current_cash,
                    "starting_budget": starting_budget,
                    "cash_display": _format_cash(current_cash),
                    "budget_display": _format_cash(starting_budget),
                    # Phase 7 / Task A7 — raw reputation / fan_trust
                    # ints DROPPED (per §17.4 "Rich Not Thin"). The
                    # finance UI shows the voice phrases only.
                    "reputation_phrase": _reputation_phrase(reputation),
                    "fan_trust_phrase": _fan_trust_phrase(fan_trust),
                },
                "monthly_burn": monthly_burn,
                "cash_flow_30d": cash_flow,
                "transactions": {
                    "items": tx_items,
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "total_pages": total_pages,
                    "filters": {
                        "transaction_type": type_filter,
                        "search": search,
                    },
                },
                "last_event_pl": last_event,
                "type_options": type_options,
            }
        except Exception as e:
            print(f"[api.get_finance_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e),
                    "promo": None, "monthly_burn": {}, "cash_flow_30d": {},
                    "transactions": {"items": [], "page": 1, "per_page": 20,
                                     "total": 0, "total_pages": 1,
                                     "filters": filters or {}},
                    "last_event_pl": None, "type_options": []}

    # ============================================================
    # P2-FINANCE-CONTRACTS — DEALS (contracts screen)
    # ============================================================
    #
    # Per docs/P2_PLAN_FINANCE_CONTRACTS.md §2:
    #   - Fighter contracts for the player's promo (paginated 20/page):
    #     fighter name, salary, start/end dates, days_until_expiry,
    #     bonus_structure (voice phrase), status chip.
    #   - Staff contracts for the player's promo: staff name, role,
    #     skill phrase, salary, end_date, days_until_expiry.
    #   - Counts of contracts expiring within 30 / 60 days (for the
    #     alert banner + filter badges).
    #
    # Voice compliance (CONVENTIONS §14):
    #   - Skill level → voice phrase ("world-class" / "established" /
    #     "promising" / "unproven"), NEVER raw 0-100.
    #   - Salary amounts OK as dollar figures (they're contracts).
    #   - Days-until-expiry OK as a number (it's a countdown).
    #   - Bonus structure → voice phrase ("75% win bonus" / "—").

    def _days_until(self, end_date_str, sim_date):
        """Return int days from sim_date until end_date (negative if past)."""
        if not end_date_str or not sim_date:
            return None
        try:
            end = datetime.strptime(str(end_date_str)[:10], "%Y-%m-%d")
            return (end - sim_date).days
        except Exception:
            return None

    def _bonus_phrase(self, bonus_json):
        """Voice phrase for a contract.bonus_structure JSON blob.

        Format: {"win_bonus_pct": 0.75, "ko_bonus": 50000, ...}
        Returns "75% win bonus" / "50% win bonus, $50K KO bonus" / "—".
        """
        if not bonus_json:
            return "—"
        try:
            bonus = json.loads(bonus_json) if isinstance(bonus_json, str) else bonus_json
        except Exception:
            return "—"
        if not isinstance(bonus, dict) or not bonus:
            return "—"
        parts = []
        if "win_bonus_pct" in bonus:
            try:
                pct = float(bonus["win_bonus_pct"] or 0)
                # Render as 0-100 percent integer (e.g. 0.75 → "75%").
                pct_str = f"{int(round(pct * 100))}%"
                parts.append(pct_str + " win bonus")
            except (TypeError, ValueError):
                pass
        if "ko_bonus" in bonus and bonus["ko_bonus"]:
            try:
                parts.append(_format_cash(float(bonus["ko_bonus"])) + " KO bonus")
            except (TypeError, ValueError):
                pass
        if "sub_bonus" in bonus and bonus["sub_bonus"]:
            try:
                parts.append(_format_cash(float(bonus["sub_bonus"])) + " sub bonus")
            except (TypeError, ValueError):
                pass
        if "performance_bonus" in bonus and bonus["performance_bonus"]:
            try:
                parts.append(_format_cash(float(bonus["performance_bonus"])) + " perf bonus")
            except (TypeError, ValueError):
                pass
        if "signing_bonus" in bonus and bonus["signing_bonus"]:
            try:
                parts.append(_format_cash(float(bonus["signing_bonus"])) + " signing")
            except (TypeError, ValueError):
                pass
        return " · ".join(parts) if parts else "—"

    @staticmethod
    def _expiry_tier(days_left):
        """Return the voice-tier label for a contract's days-until-expiry.

        - "expired" — days_left < 0 (shouldn't normally appear since
          we filter to status='active', but defensive).
        - "critical" — ≤30 days (red).
        - "soon" — ≤60 days (yellow).
        - "ok" — >60 days (green).
        - "unknown" — None (no end_date or no sim_date).
        """
        if days_left is None:
            return "unknown"
        if days_left < 0:
            return "expired"
        if days_left <= 30:
            return "critical"
        if days_left <= 60:
            return "soon"
        return "ok"

    def get_contracts_data(self, page=1, filters=None):
        """Return paginated fighter + staff contracts for the player's promo.

        Args:
          page:    int page number (1-indexed, 20 fighter contracts per page)
          filters: {
            "tab": "all"|"expiring_soon"|"fighters"|"staff"  (default "all")
            "search": str  (substring match on fighter/staff name)
          }

        Returns:
          {
            "promo": {"promotion_id", "name"},
            "counts": {
              "active_fighter_contracts", "active_staff_contracts",
              "expiring_30d", "expiring_60d", "total_active"
            },
            "filter": {"tab", "search"},
            "fighter_contracts": {
              "items": [{
                "contract_id", "fighter_id", "fighter_name", "nickname",
                "salary", "salary_display",
                "start_date", "end_date",
                "start_date_display", "end_date_display",
                "days_until_expiry", "expiry_tier",
                "bonus_phrase", "bonus_structure",
                "buyout_clause", "buyout_display",
                "exclusive_flag", "contract_type",
                "status", "status_label"
              }],
              "page", "per_page": 20, "total", "total_pages"
            },
            "staff_contracts": {
              "items": [{
                "contract_id", "staff_id", "staff_name",
                "role_type", "role_label",
                "skill_phrase", "skill_level" (NEVER displayed raw),
                "salary", "salary_display",
                "start_date", "end_date",
                "start_date_display", "end_date_display",
                "days_until_expiry", "expiry_tier",
                "buyout_clause", "buyout_display",
                "exclusive_flag", "status", "status_label"
              }],
              "total"
            },
            "sim_date"
          }

        expiry_tier values: "expired" (<0 days), "critical" (≤30),
        "soon" (≤60), "ok" (>60), "unknown" (None).
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected."}
            conn = self.conn
            filters = filters or {}
            tab = (filters.get("tab") or "all").lower()
            if tab not in ("all", "expiring_soon", "fighters", "staff"):
                tab = "all"
            search = (filters.get("search") or "").strip()
            page = max(1, int(page or 1))
            per_page = 20

            # --- Sim date for days_until_expiry computation ---
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            sim_date = None
            if sim_date_str:
                try:
                    sim_date = datetime.strptime(
                        str(sim_date_str)[:10], "%Y-%m-%d")
                except Exception:
                    sim_date = None

            p_name_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?",
                (pid,),
            ).fetchone()
            p_name = p_name_row[0] if p_name_row else "Your Promotion"

            # --- Fighter contracts (active only) ---
            # Pre-build the WHERE + base query so we can reuse it for
            # the count + the page fetch. Order by end_date ASC so the
            # soonest-expiring contracts surface to the top (the player
            # needs to act on those first).
            fc_where = (
                "c.promotion_id=? AND c.status='active' "
                "AND c.contract_target_type='fighter'"
            )
            fc_params = [pid]
            if search:
                fc_where += (" AND ((f.first_name || ' ' || f.last_name) "
                             "LIKE ? OR f.first_name LIKE ? OR f.last_name LIKE ?)")
                like = "%" + search + "%"
                fc_params.extend([like, like, like])

            fc_total = int(conn.execute(
                f"SELECT COUNT(*) FROM contracts c "
                f"JOIN fighter_contracts fc ON fc.contract_id=c.contract_id "
                f"JOIN fighters f ON f.fighter_id=fc.fighter_id "
                f"WHERE {fc_where}",
                fc_params,
            ).fetchone()[0] or 0)

            fc_total_pages = max(1, (fc_total + per_page - 1) // per_page)
            fc_page = min(page, fc_total_pages)
            fc_offset = (fc_page - 1) * per_page

            fc_rows = conn.execute(
                f"SELECT c.contract_id, c.start_date, c.end_date, c.salary, "
                f"      c.bonus_structure, c.buyout_clause, c.exclusive_flag, "
                f"      c.status, fc.fighter_id, fc.contract_type, "
                f"      f.first_name, f.last_name, f.nickname "
                f"FROM contracts c "
                f"JOIN fighter_contracts fc ON fc.contract_id=c.contract_id "
                f"JOIN fighters f ON f.fighter_id=fc.fighter_id "
                f"WHERE {fc_where} "
                f"ORDER BY c.end_date ASC, c.salary DESC "
                f"LIMIT ? OFFSET ?",
                fc_params + [per_page, fc_offset],
            ).fetchall()

            fighter_items = []
            expiring_30d = 0
            expiring_60d = 0
            for r in fc_rows:
                (cid, sd, ed, sal, bonus, buyout, excl, status,
                 fid, ctype, fn, ln, nick) = r
                days_left = self._days_until(ed, sim_date)
                tier = self._expiry_tier(days_left)
                if days_left is not None and days_left >= 0:
                    if days_left <= 30:
                        expiring_30d += 1
                    if days_left <= 60:
                        expiring_60d += 1
                salary = float(sal or 0)
                buyout_val = float(buyout) if buyout is not None else None
                fighter_items.append({
                    "contract_id": cid,
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "nickname": nick or "",
                    "salary": salary,
                    "salary_display": _format_cash(salary) + "/yr",
                    "start_date": sd or "",
                    "end_date": ed or "",
                    "start_date_display": _format_long_date(sd),
                    "end_date_display": _format_long_date(ed),
                    "days_until_expiry": days_left,
                    "expiry_tier": tier,
                    "bonus_phrase": self._bonus_phrase(bonus),
                    "bonus_structure": bonus,
                    "buyout_clause": buyout_val,
                    "buyout_display": (
                        _format_cash(buyout_val) if buyout_val is not None
                        else "—"),
                    "exclusive_flag": bool(excl),
                    "contract_type": ctype or "standard",
                    "status": status,
                    "status_label": status.title() if status else "—",
                })

            # --- Staff contracts (active only) ---
            # Not paginated — typically <30 staff contracts per promo.
            # Same end_date ASC ordering so expiring staff surface first.
            sc_where = (
                "c.promotion_id=? AND c.status='active' "
                "AND c.contract_target_type='staff'"
            )
            sc_params = [pid]
            if search:
                sc_where += (" AND ((s.first_name || ' ' || s.last_name) "
                             "LIKE ? OR s.first_name LIKE ? OR s.last_name LIKE ?)")
                like = "%" + search + "%"
                sc_params.extend([like, like, like])

            sc_rows = conn.execute(
                f"SELECT c.contract_id, c.start_date, c.end_date, c.salary, "
                f"      c.buyout_clause, c.exclusive_flag, c.status, "
                f"      sc.staff_id, sc.contract_role, "
                f"      s.first_name, s.last_name, s.role_type, s.skill_level "
                f"FROM contracts c "
                f"JOIN staff_contracts sc ON sc.contract_id=c.contract_id "
                f"JOIN staff s ON s.staff_id=sc.staff_id "
                f"WHERE {sc_where} "
                f"ORDER BY c.end_date ASC, c.salary DESC",
                sc_params,
            ).fetchall()

            staff_items = []
            for r in sc_rows:
                (cid, sd, ed, sal, buyout, excl, status,
                 sid, srole, fn, ln, role_type, skill_level) = r
                days_left = self._days_until(ed, sim_date)
                tier = self._expiry_tier(days_left)
                if days_left is not None and days_left >= 0:
                    if days_left <= 30:
                        expiring_30d += 1
                    if days_left <= 60:
                        expiring_60d += 1
                salary = float(sal or 0)
                buyout_val = float(buyout) if buyout is not None else None
                staff_items.append({
                    "contract_id": cid,
                    "staff_id": sid,
                    "staff_name": f"{fn or ''} {ln or ''}".strip(),
                    "role_type": role_type or srole or "—",
                    "role_label": _role_label(role_type or srole),
                    "skill_phrase": _skill_phrase(skill_level),
                    "skill_level": int(skill_level) if skill_level is not None else None,
                    "salary": salary,
                    "salary_display": _format_cash(salary) + "/yr",
                    "start_date": sd or "",
                    "end_date": ed or "",
                    "start_date_display": _format_long_date(sd),
                    "end_date_display": _format_long_date(ed),
                    "days_until_expiry": days_left,
                    "expiry_tier": tier,
                    "buyout_clause": buyout_val,
                    "buyout_display": (
                        _format_cash(buyout_val) if buyout_val is not None
                        else "—"),
                    "exclusive_flag": bool(excl),
                    "status": status,
                    "status_label": status.title() if status else "—",
                })

            # Apply tab filter to the displayed lists.
            # - "all": show both fighter + staff lists.
            # - "fighters": show fighters only.
            # - "staff": show staff only.
            # - "expiring_soon": show only contracts with expiry_tier
            #   in (critical, soon, expired) — i.e. ≤60 days. Both
            #   lists shown, but pre-filtered to expiring only.
            display_fighters = fighter_items
            display_staff = staff_items
            if tab == "fighters":
                display_staff = []
            elif tab == "staff":
                display_fighters = []
            elif tab == "expiring_soon":
                display_fighters = [f for f in fighter_items
                                    if f["expiry_tier"] in ("critical", "soon", "expired")]
                display_staff = [s for s in staff_items
                                 if s["expiry_tier"] in ("critical", "soon", "expired")]

            return {
                "promo": {"promotion_id": pid, "name": p_name},
                "counts": {
                    "active_fighter_contracts": fc_total,
                    "active_staff_contracts": len(staff_items),
                    "expiring_30d": expiring_30d,
                    "expiring_60d": expiring_60d,
                    "total_active": fc_total + len(staff_items),
                },
                "filter": {"tab": tab, "search": search},
                "fighter_contracts": {
                    "items": display_fighters,
                    "page": fc_page,
                    "per_page": per_page,
                    "total": fc_total,
                    "total_pages": fc_total_pages,
                },
                "staff_contracts": {
                    "items": display_staff,
                    "total": len(staff_items),
                },
                "sim_date": sim_date_str,
            }
        except Exception as e:
            print(f"[api.get_contracts_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e),
                    "promo": None, "counts": {}, "filter": filters or {},
                    "fighter_contracts": {"items": [], "page": 1, "per_page": 20,
                                          "total": 0, "total_pages": 1},
                    "staff_contracts": {"items": [], "total": 0},
                    "sim_date": None}

    # ============================================================
    # P3 — AGENT OFFERS (mystery-box talent signing)
    # ============================================================
    #
    # Per docs/P3_P4_PLAN.md §P3 + CONVENTIONS §13/§14:
    #   - Talent Hunter fantasy (Discovery pillar). The player sees a
    #     voice-layer vague scouting report — NEVER the fighter's name,
    #     raw attributes, potential, or career record (CONVENTIONS §14).
    #   - The asking_price is currency (allowed by §14 — currency is
    #     not a fighter attribute).
    #   - The fighter_id is included in the offer payload ONLY so the
    #     resolve call can act on it — the JS layer never displays it.
    #   - On accept: the fighter's identity is REVEALED (name + fighter_id
    #     returned) so the UI can toast "It's... [Fighter Name]!" and
    #     navigate to the Fighter Profile.
    #
    # The backend logic lives in src/agent_offers.py — these are thin
    # API wrappers that translate sqlite3.Row tuples into JSON dicts
    # with voice phrases + display strings.

    # Offer type → player-facing label + chip color (matches the brief's
    # three flavors: Mystery Prospect / Established Fighter / Comeback
    # Veteran). The five DB offer_types collapse into these three so the
    # UI shows the player an intuitive framing, not the internal name.
    _OFFER_TYPE_META = {
        # Brand-new fighters — mystery box flavor.
        "unknown_talent":   ("Mystery Prospect",    "gold"),
        "prospect_gamble":  ("Mystery Prospect",    "gold"),
        # Existing free agents with a track record.
        "style_specialist": ("Established Fighter", "gold"),
        "contender_release":("Established Fighter", "gold"),
        # Veterans past their prime.
        "washout_veteran":  ("Comeback Veteran",    "warning"),
    }

    @staticmethod
    def _offer_type_meta(offer_type):
        """Return (label, chip_color_class) for an offer_type.

        Defensive — unknown types fall back to a generic gold chip so
        the UI never breaks on a future offer_type addition.
        """
        return Api._OFFER_TYPE_META.get(
            offer_type or "", ("Agent Offer", "gold"))

    def get_agent_offers(self):
        """Return all active (unresolved) agent offers for the player's promo.

        Each offer carries:
          - offer_id (for the resolve call)
          - fighter_id (HIDDEN from the UI — used only as a key)
          - fighter_description (voice-layer scouting report — the
            only fighter info the player sees pre-signing)
          - offer_type + offer_type_label + offer_type_color
          - asking_price + asking_price_display
          - offer_date + expires_date + days_until_expiry + expiry_tier
            (red ≤1 day, warning ≤3 days, ok otherwise)

        Returns:
          {
            "promo": {"promotion_id", "name"},
            "offers": [<offer>, ...],
            "active_count": N,
            "sim_date": "YYYY-MM-DD",
            "player_cash": REAL,
            "player_cash_display": "$89M"
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected.",
                        "offers": [], "active_count": 0}
            conn = self.conn

            # Sim date for days-until-expiry computation.
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            sim_date = None
            if sim_date_str:
                try:
                    sim_date = datetime.strptime(
                        str(sim_date_str)[:10], "%Y-%m-%d")
                except Exception:
                    sim_date = None

            # Promo name + player's current cash (for the "Sign for $X"
            # button affordance — disabled when cash < asking_price).
            p_row = conn.execute(
                "SELECT name, current_cash FROM promotions "
                "WHERE promotion_id=?", (pid,)).fetchone()
            if not p_row:
                return {"ok": False, "error": "Promotion not found.",
                        "offers": [], "active_count": 0}
            promo_name = p_row[0] or "Your Promotion"
            player_cash = float(p_row[1] or 0)

            # Use the agent_offers reader — keeps the WHERE clause
            # centralized in the source-of-truth module.
            try:
                from agent_offers import get_active_offers
            except Exception as e:
                return {"ok": False,
                        "error": f"agent_offers module unavailable: {e}",
                        "offers": [], "active_count": 0}
            rows = get_active_offers(conn, promotion_id=pid)

            offers = []
            # agent_offers column order (from build_db.py CREATE TABLE):
            #   0:offer_id 1:promotion_id 2:fighter_id 3:offer_date
            #   4:offer_type 5:asking_price 6:fighter_description
            #   7:is_resolved 8:resolution 9:resolution_date
            #   10:expires_date 11:created_at
            for r in rows:
                offer_id = r[0]
                fighter_id = r[2]
                offer_type = r[4]
                asking_price = float(r[5] or 0)
                description = r[6] or ""
                offer_date = r[3] or ""
                expires_date = r[10] or ""

                days_left = self._days_until(expires_date, sim_date)
                tier = self._offer_expiry_tier(days_left)
                label, chip_color = self._offer_type_meta(offer_type)

                # Sign affordance — only true when the player can
                # actually afford the asking price. UI uses this to
                # enable/disable the Sign button.
                can_afford = player_cash >= asking_price

                offers.append({
                    "offer_id": offer_id,
                    "fighter_id": fighter_id,  # hidden from UI
                    "offer_type": offer_type,
                    "offer_type_label": label,
                    "offer_type_color": chip_color,
                    "asking_price": asking_price,
                    "asking_price_display": _format_cash(asking_price),
                    "fighter_description": description,
                    "offer_date": offer_date,
                    "offer_date_display": _format_long_date(offer_date),
                    "expires_date": expires_date,
                    "expires_date_display": _format_long_date(expires_date),
                    "days_until_expiry": days_left,
                    "expiry_tier": tier,
                    "can_afford": can_afford,
                })

            # Sort by expiry ASC (most urgent first) — keeps the
            # "expires in 1 day" offers at the top of the list.
            offers.sort(key=lambda o: (
                o["days_until_expiry"] if o["days_until_expiry"] is not None
                else 9999))

            return {
                "ok": True,
                "promo": {"promotion_id": pid, "name": promo_name},
                "offers": offers,
                "active_count": len(offers),
                "sim_date": sim_date_str,
                "player_cash": player_cash,
                "player_cash_display": _format_cash(player_cash),
            }
        except Exception as e:
            print(f"[api.get_agent_offers] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e),
                    "offers": [], "active_count": 0}

    @staticmethod
    def _offer_expiry_tier(days_left):
        """Voice-tier label for an agent offer's days-until-expiry.

        Tighter than contract expiry — agent offers expire in 14 days,
        so the thresholds are:
          - "expired" — days_left < 0 (defensive — backend should have
            auto-expired these via the TICK_ADVANCED subscriber).
          - "critical" — ≤1 day (red, "expires today" / "expires in 1 day")
          - "soon" — ≤3 days (warning yellow — running out of time)
          - "ok" — >3 days
          - "unknown" — None (no expires_date or no sim_date).
        """
        if days_left is None:
            return "unknown"
        if days_left < 0:
            return "expired"
        if days_left <= 1:
            return "critical"
        if days_left <= 3:
            return "soon"
        return "ok"

    def resolve_agent_offer(self, offer_id, accept=True):
        """Resolve an agent offer — sign the fighter or pass.

        Calls agent_offers.resolve_offer under the hood. On accept,
        returns the fighter's identity so the UI can do the "reveal"
        toast + navigate to Fighter Profile.

        Args:
          offer_id: the agent_offers.offer_id to resolve.
          accept: True → sign the fighter (deducts asking_price from
            promo cash + sets fighter.current_promotion_id). False →
            mark as rejected (fighter remains a free agent).

        Returns (accept):
          {
            "ok": True,
            "accepted": True,
            "offer_id": N,
            "fighter_id": N,
            "fighter_name": "John Vale",
            "fighter_nickname": "The Hammer" | "",
            "asking_price": REAL,
            "asking_price_display": "$56K",
            "remaining_cash": REAL,
            "remaining_cash_display": "$88M",
            "resolution": "signed",
            "reason": ""
          }

        Returns (decline):
          {
            "ok": True,
            "accepted": False,
            "offer_id": N,
            "fighter_id": N,
            "resolution": "rejected",
            "reason": ""
          }

        Returns (failure — fighter no longer available, can't afford,
        already resolved, etc.):
          {
            "ok": False,
            "accepted": False,
            "offer_id": N,
            "fighter_id": N,
            "resolution": "rejected",
            "reason": "Insufficient cash — needs $56K, you have $10K"
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected.",
                        "accepted": False, "offer_id": offer_id,
                        "resolution": "rejected", "reason": "no promo"}
            try:
                offer_id = int(offer_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": "Invalid offer_id.",
                        "accepted": False, "offer_id": offer_id,
                        "resolution": "rejected", "reason": "bad offer_id"}
            accept_flag = bool(accept)

            # Pre-fetch the fighter_id so we can return it even on the
            # reject path (the UI may want to navigate to the fighter
            # profile post-rejection for context — currently it doesn't,
            # but having the data makes the API self-contained).
            conn = self.conn
            pre_row = conn.execute(
                "SELECT fighter_id, asking_price FROM agent_offers "
                "WHERE offer_id=? AND promotion_id=?",
                (offer_id, pid),
            ).fetchone()
            if not pre_row:
                return {"ok": False,
                        "error": "Offer not found or not for your promotion.",
                        "accepted": False, "offer_id": offer_id,
                        "resolution": "rejected",
                        "reason": "offer not found"}
            fighter_id = pre_row[0]
            asking_price = float(pre_row[1] or 0)

            # Call the backend resolver. It commits within the same
            # connection (the conn is shared). Returns True on success.
            from agent_offers import resolve_offer
            success = resolve_offer(
                conn, offer_id, accept=accept_flag,
            )
            conn.commit()

            if not accept_flag:
                # Reject path — always succeeds (just marks the row).
                return {
                    "ok": True,
                    "accepted": False,
                    "offer_id": offer_id,
                    "fighter_id": fighter_id,
                    "resolution": "rejected",
                    "asking_price": asking_price,
                    "asking_price_display": _format_cash(asking_price),
                    "reason": "",
                }

            if not success:
                # Accept path failed — backend printed a warning.
                # Possible causes: fighter already signed elsewhere,
                # retired/inactive, promotion can't afford, offer
                # already resolved. Surface a friendly reason.
                # Re-read the offer to see if it's already resolved.
                reread = conn.execute(
                    "SELECT is_resolved, resolution FROM agent_offers "
                    "WHERE offer_id=?", (offer_id,),
                ).fetchone()
                reason = "Sign failed — the deal fell through."
                resolution = "rejected"
                if reread and reread[0]:
                    res = reread[1] or "rejected"
                    if res == "signed":
                        # Already signed — shouldn't happen, but defensive.
                        reason = "Offer was already signed."
                        resolution = "signed"
                    elif res == "expired":
                        reason = "Offer expired before you could sign."
                        resolution = "expired"
                    elif res == "rejected":
                        # Either the player's previous reject, or the
                        # backend's defensive reject (fighter no longer
                        # available / promo can't afford). Surface a
                        # targeted reason.
                        cash_row = conn.execute(
                            "SELECT current_cash FROM promotions "
                            "WHERE promotion_id=?", (pid,)).fetchone()
                        cash_now = float(cash_row[0] or 0) if cash_row else 0.0
                        if cash_now < asking_price:
                            reason = (f"Insufficient cash — needs "
                                      f"{_format_cash(asking_price)}, "
                                      f"you have {_format_cash(cash_now)}.")
                        else:
                            reason = ("Fighter is no longer available — "
                                      "another promotion signed them, or "
                                      "they retired/inactivated.")
                return {
                    "ok": False,
                    "accepted": False,
                    "offer_id": offer_id,
                    "fighter_id": fighter_id,
                    "resolution": resolution,
                    "asking_price": asking_price,
                    "asking_price_display": _format_cash(asking_price),
                    "reason": reason,
                }

            # Success — fetch the fighter's identity for the reveal.
            f_row = conn.execute(
                "SELECT first_name, last_name, nickname FROM fighters "
                "WHERE fighter_id=?", (fighter_id,),
            ).fetchone()
            if f_row:
                fn, ln, nick = f_row
                fighter_name = f"{fn or ''} {ln or ''}".strip()
                fighter_nickname = nick or ""
            else:
                fighter_name = "Unknown Fighter"
                fighter_nickname = ""

            cash_row = conn.execute(
                "SELECT current_cash FROM promotions "
                "WHERE promotion_id=?", (pid,)).fetchone()
            remaining_cash = float(cash_row[0] or 0) if cash_row else 0.0

            return {
                "ok": True,
                "accepted": True,
                "offer_id": offer_id,
                "fighter_id": fighter_id,
                "fighter_name": fighter_name,
                "fighter_nickname": fighter_nickname,
                "asking_price": asking_price,
                "asking_price_display": _format_cash(asking_price),
                "remaining_cash": remaining_cash,
                "remaining_cash_display": _format_cash(remaining_cash),
                "resolution": "signed",
                "reason": "",
            }
        except Exception as e:
            print(f"[api.resolve_agent_offer] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e),
                    "accepted": False, "offer_id": offer_id,
                    "resolution": "rejected", "reason": str(e)}

    # ============================================================
    # P4 — RECORD BOOK (all-time leaders)
    # ============================================================
    #
    # Per docs/P3_P4_PLAN.md §P4 + CONVENTIONS §13 (Historian fantasy
    # — Legacy pillar). No new table — computes all-time records on
    # the fly from fight_history + fighter_career + titles + rivalries
    # + fighters. This is the "what stories does the world remember?"
    # screen.
    #
    # Voice compliance (CONVENTIONS §14):
    #   - Career record (W-L-D) is OK as numbers — these are public
    #     career stats, not hidden attributes. The player has always
    #     seen them on the Fighter Profile screen.
    #   - Age is OK as a number for "oldest/youngest fighter" — age
    #     is observable public record, not a hidden attribute. The
    #     prohibition in §14 is on potential/attribute numbers, not
    #     biographical facts.
    #   - Win % is OK as a number — it's a derived career stat.
    #   - Title reigns + defenses are OK as counts — they're career
    #     achievements, not hidden ratings.
    #   - Each record carries a voice "context" phrase (e.g.
    #     "32-20-4 career record") so the player gets narrative, not
    #     just a bare number.

    def get_records_data(self):
        """Return all-time records computed from existing DB data.

        Computes 12 records (matches the spec list):
          1. Most wins (all-time) — fighter_career.record_wins DESC
          2. Most KO/TKO wins — fight_history outcome='win' +
             result_type IN ('ko_tko','ko','tko') DESC
          3. Most submission wins — fight_history outcome='win' +
             result_type='submission' DESC
          4. Most title reigns — fighter_career.title_reigns DESC
          5. Most title defenses — SUM(titles.title_defenses_count)
             per current champion DESC
          6. Longest active win streak — fighter_career.win_streak DESC
             (current streak — labeled "ACTIVE" since we don't have a
             historical longest_win_streak column)
          7. Most fights — (wins + losses + draws) DESC
          8. Best win % (min 10 fights) — wins / total DESC
          9. Most rivalries — COUNT(rivalries WHERE fighter_a OR b) DESC
          10. Oldest active fighter — date_of_birth ASC
          11. Youngest active fighter — date_of_birth DESC
          12. (champions list — separate, see below)

        Plus a current_champions list (all current title holders
        across all promotions, sorted by defenses DESC then reign
        length DESC) — the player can see who's holding gold right now.

        Returns:
          {
            "promo": {"promotion_id", "name"},
            "records": [<record>, ...],
            "champions": {
              "count": N,
              "items": [<champion>, ...]  // top 12 by defenses
            },
            "sim_date": "YYYY-MM-DD"
          }

        Each record:
          {
            "key": "most_wins",
            "title": "MOST WINS",
            "icon": "🥇",
            "tier": "gold",  // gold|green|crimson|white — visual variety
            "fighter_id": N,
            "fighter_name": "Anthony Perez",
            "fighter_nickname": "" | "Queen",
            "value": 32,  // raw number
            "value_display": "32",  // formatted string
            "context": "32-20-4 career record"  // voice phrase
          }
          If no fighter qualifies (e.g. zero active fighters), the
          record is returned with fighter_id=None and an empty
          context so the UI shows a placeholder.

        Each champion:
          {
            "fighter_id", "fighter_name", "fighter_nickname",
            "promotion_id", "promotion_name",
            "weight_class_id", "weight_class_name",
            "champion_since_date", "reign_length" (e.g. "2y 6m"),
            "title_defenses_count", "title_reigns_count"
          }
        """
        try:
            pid = self.get_player_promotion()
            if not pid:
                return {"ok": False, "error": "No player promotion selected.",
                        "records": [], "champions": {"count": 0, "items": []}}
            conn = self.conn

            # Sim date for reign-length computation + age calc.
            clock = get_clock(conn)
            sim_date_str = clock[0] if clock else None
            sim_date = None
            if sim_date_str:
                try:
                    sim_date = datetime.strptime(
                        str(sim_date_str)[:10], "%Y-%m-%d")
                except Exception:
                    sim_date = None

            p_row = conn.execute(
                "SELECT name FROM promotions WHERE promotion_id=?",
                (pid,)).fetchone()
            promo_name = p_row[0] if p_row else "Your Promotion"

            records = []

            # ---- 1. Most wins ----
            row = conn.execute(
                "SELECT fc.fighter_id, f.first_name, f.last_name, f.nickname, "
                "fc.record_wins, fc.record_losses, fc.record_draws "
                "FROM fighter_career fc "
                "JOIN fighters f ON f.fighter_id=fc.fighter_id "
                "WHERE fc.record_wins > 0 "
                "ORDER BY fc.record_wins DESC, fc.record_losses ASC "
                "LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, w, l, d = row
                records.append({
                    "key": "most_wins",
                    "title": "MOST WINS",
                    "icon": "🥇",
                    "tier": "gold",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": w,
                    "value_display": str(w),
                    "context": f"{w}-{l}-{d} career record",
                })

            # ---- 2. Most KO/TKO wins ----
            row = conn.execute(
                "SELECT fh.fighter_id, f.first_name, f.last_name, f.nickname, "
                "COUNT(*) AS kos "
                "FROM fight_history fh "
                "JOIN fighters f ON f.fighter_id=fh.fighter_id "
                "WHERE fh.outcome='win' "
                "AND fh.result_type IN ('ko_tko','ko','tko') "
                "GROUP BY fh.fighter_id "
                "ORDER BY kos DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, kos = row
                # Pull the fighter's career record for context.
                cr = conn.execute(
                    "SELECT record_wins, record_losses, record_draws "
                    "FROM fighter_career WHERE fighter_id=?", (fid,)).fetchone()
                ctx = (f"{kos} finishes by knockout or TKO"
                       if cr is None else
                       f"{kos} of {cr[0]} wins by knockout or TKO")
                records.append({
                    "key": "most_ko_wins",
                    "title": "MOST KO/TKO WINS",
                    "icon": "💥",
                    "tier": "crimson",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": kos,
                    "value_display": str(kos),
                    "context": ctx,
                })

            # ---- 3. Most submission wins ----
            row = conn.execute(
                "SELECT fh.fighter_id, f.first_name, f.last_name, f.nickname, "
                "COUNT(*) AS subs "
                "FROM fight_history fh "
                "JOIN fighters f ON f.fighter_id=fh.fighter_id "
                "WHERE fh.outcome='win' AND fh.result_type='submission' "
                "GROUP BY fh.fighter_id "
                "ORDER BY subs DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, subs = row
                cr = conn.execute(
                    "SELECT record_wins FROM fighter_career "
                    "WHERE fighter_id=?", (fid,)).fetchone()
                ctx = (f"{subs} finishes by submission"
                       if cr is None else
                       f"{subs} of {cr[0]} wins by submission")
                records.append({
                    "key": "most_sub_wins",
                    "title": "MOST SUBMISSION WINS",
                    "icon": "🤼",
                    "tier": "green",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": subs,
                    "value_display": str(subs),
                    "context": ctx,
                })

            # ---- 4. Most title reigns ----
            row = conn.execute(
                "SELECT fc.fighter_id, f.first_name, f.last_name, f.nickname, "
                "fc.title_reigns, fc.record_wins, fc.record_losses, fc.record_draws "
                "FROM fighter_career fc "
                "JOIN fighters f ON f.fighter_id=fc.fighter_id "
                "WHERE fc.title_reigns > 0 "
                "ORDER BY fc.title_reigns DESC, fc.record_wins DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, reigns, w, l, d = row
                records.append({
                    "key": "most_title_reigns",
                    "title": "MOST TITLE REIGNS",
                    "icon": "👑",
                    "tier": "gold",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": reigns,
                    "value_display": str(reigns),
                    "context": (f"{reigns} title reigns · {w}-{l}-{d} "
                                f"career record"),
                })

            # ---- 5. Most title defenses (current champions only) ----
            # SUM across all belts the fighter currently holds.
            row = conn.execute(
                "SELECT t.current_champion_fighter_id, "
                "f.first_name, f.last_name, f.nickname, "
                "SUM(t.title_defenses_count) AS total_defs, "
                "COUNT(*) AS n_belts "
                "FROM titles t "
                "JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id "
                "WHERE t.is_vacant=0 AND t.current_champion_fighter_id IS NOT NULL "
                "GROUP BY t.current_champion_fighter_id "
                "ORDER BY total_defs DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, defs, n_belts = row
                belt_phrase = ("holding " + str(n_belts) + " belt" +
                               ("s" if n_belts != 1 else ""))
                records.append({
                    "key": "most_title_defenses",
                    "title": "MOST TITLE DEFENSES",
                    "icon": "🛡",
                    "tier": "gold",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": defs,
                    "value_display": str(defs),
                    "context": f"{defs} successful defenses · {belt_phrase}",
                })

            # ---- 6. Longest active win streak ----
            # NOTE: fighter_career.win_streak is the CURRENT streak
            # (not historical longest). Labeled "ACTIVE" so the player
            # understands what they're seeing. A historical longest
            # column would require a schema migration + backfill — out
            # of scope for P4.
            row = conn.execute(
                "SELECT fc.fighter_id, f.first_name, f.last_name, f.nickname, "
                "fc.win_streak, fc.record_wins, fc.record_losses, fc.record_draws "
                "FROM fighter_career fc "
                "JOIN fighters f ON f.fighter_id=fc.fighter_id "
                "WHERE fc.win_streak > 0 "
                "ORDER BY fc.win_streak DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, streak, w, l, d = row
                records.append({
                    "key": "longest_win_streak",
                    "title": "LONGEST ACTIVE WIN STREAK",
                    "icon": "🔥",
                    "tier": "crimson",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": streak,
                    "value_display": str(streak),
                    "context": f"{streak}-fight win streak · {w}-{l}-{d} career",
                })

            # ---- 7. Most fights ----
            row = conn.execute(
                "SELECT fc.fighter_id, f.first_name, f.last_name, f.nickname, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "(fc.record_wins + fc.record_losses + fc.record_draws) AS total "
                "FROM fighter_career fc "
                "JOIN fighters f ON f.fighter_id=fc.fighter_id "
                "ORDER BY total DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, w, l, d, total = row
                records.append({
                    "key": "most_fights",
                    "title": "MOST FIGHTS",
                    "icon": "🏟",
                    "tier": "white",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": total,
                    "value_display": str(total),
                    "context": f"{total} career fights · {w}-{l}-{d}",
                })

            # ---- 8. Best win % (min 10 fights) ----
            row = conn.execute(
                "SELECT fc.fighter_id, f.first_name, f.last_name, f.nickname, "
                "fc.record_wins, fc.record_losses, fc.record_draws, "
                "(fc.record_wins * 1.0 / "
                " (fc.record_wins + fc.record_losses + fc.record_draws)) AS pct "
                "FROM fighter_career fc "
                "JOIN fighters f ON f.fighter_id=fc.fighter_id "
                "WHERE (fc.record_wins + fc.record_losses + fc.record_draws) >= 10 "
                "ORDER BY pct DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, w, l, d, pct = row
                pct_int = int(round(float(pct) * 100))
                records.append({
                    "key": "best_win_pct",
                    "title": "BEST WIN %",
                    "icon": "📈",
                    "tier": "green",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": pct_int,
                    "value_display": str(pct_int) + "%",
                    "context": f"{w}-{l}-{d} career record · {pct_int}% win rate",
                })

            # ---- 9. Most rivalries (active) ----
            # A fighter can be either fighter_a or fighter_b — sum both.
            row = conn.execute(
                "SELECT fighter_id, MAX(n_rivals) AS max_n FROM ( "
                "  SELECT fighter_a_id AS fighter_id, COUNT(*) AS n_rivals "
                "  FROM rivalries WHERE is_active=1 "
                "  GROUP BY fighter_a_id "
                "  UNION ALL "
                "  SELECT fighter_b_id AS fighter_id, COUNT(*) AS n_rivals "
                "  FROM rivalries WHERE is_active=1 "
                "  GROUP BY fighter_b_id "
                ") GROUP BY fighter_id ORDER BY max_n DESC LIMIT 1"
            ).fetchone()
            if row and row[0] is not None:
                fid, n_riv = row
                f_row = conn.execute(
                    "SELECT first_name, last_name, nickname FROM fighters "
                    "WHERE fighter_id=?", (fid,)).fetchone()
                if f_row:
                    fn, ln, nick = f_row
                    records.append({
                        "key": "most_rivalries",
                        "title": "MOST RIVALRIES",
                        "icon": "💢",
                        "tier": "crimson",
                        "fighter_id": fid,
                        "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                        "fighter_nickname": nick or "",
                        "value": n_riv,
                        "value_display": str(n_riv),
                        "context": (f"{n_riv} active rivalries — no one "
                                    f"wants to see this fighter lose more"),
                    })

            # ---- 10. Oldest active fighter ----
            row = conn.execute(
                "SELECT fighter_id, first_name, last_name, nickname, date_of_birth "
                "FROM fighters "
                "WHERE is_active=1 AND is_retired=0 "
                "AND date_of_birth IS NOT NULL AND date_of_birth != '' "
                "ORDER BY date_of_birth ASC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, dob = row
                age = self._age_from_dob(dob, sim_date)
                records.append({
                    "key": "oldest_fighter",
                    "title": "OLDEST ACTIVE FIGHTER",
                    "icon": "👴",
                    "tier": "white",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": age if age is not None else 0,
                    "value_display": (str(age) if age is not None else "—"),
                    "context": (f"{age} years old · born "
                                f"{_format_long_date(dob)}"
                                if age is not None else
                                f"born {_format_long_date(dob)}"),
                })

            # ---- 11. Youngest active fighter ----
            row = conn.execute(
                "SELECT fighter_id, first_name, last_name, nickname, date_of_birth "
                "FROM fighters "
                "WHERE is_active=1 AND is_retired=0 "
                "AND date_of_birth IS NOT NULL AND date_of_birth != '' "
                "ORDER BY date_of_birth DESC LIMIT 1"
            ).fetchone()
            if row:
                fid, fn, ln, nick, dob = row
                age = self._age_from_dob(dob, sim_date)
                records.append({
                    "key": "youngest_fighter",
                    "title": "YOUNGEST ACTIVE FIGHTER",
                    "icon": "🌱",
                    "tier": "green",
                    "fighter_id": fid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "value": age if age is not None else 0,
                    "value_display": (str(age) if age is not None else "—"),
                    "context": (f"{age} years old · born "
                                f"{_format_long_date(dob)}"
                                if age is not None else
                                f"born {_format_long_date(dob)}"),
                })

            # ---- Current champions (all promos, top 12 by defenses) ----
            champ_rows = conn.execute(
                "SELECT t.current_champion_fighter_id, "
                "f.first_name, f.last_name, f.nickname, "
                "t.promotion_id, p.name AS promo_name, "
                "t.weight_class_id, wc.name AS wc_name, "
                "t.champion_since_date, t.title_defenses_count, "
                "t.title_reigns_count "
                "FROM titles t "
                "JOIN fighters f ON f.fighter_id=t.current_champion_fighter_id "
                "JOIN promotions p ON p.promotion_id=t.promotion_id "
                "JOIN weight_classes wc ON wc.weight_class_id=t.weight_class_id "
                "WHERE t.is_vacant=0 AND t.current_champion_fighter_id IS NOT NULL "
                "ORDER BY t.title_defenses_count DESC, "
                "t.champion_since_date ASC LIMIT 12"
            ).fetchall()
            champions = []
            for r in champ_rows:
                (cfid, fn, ln, nick, cpid, pname, wcid, wcname,
                 since, defs, reigns) = r
                reign = _reign_length(since, sim_date_str) if since else "—"
                # _reign_length can return negative values when the
                # champion_since_date is in the future (a known data
                # issue from past test runs). Clamp negative reigns to
                # "newly crowned" so the UI doesn't show "-2m".
                if reign and reign.startswith("-"):
                    reign = "newly crowned"
                champions.append({
                    "fighter_id": cfid,
                    "fighter_name": f"{fn or ''} {ln or ''}".strip(),
                    "fighter_nickname": nick or "",
                    "promotion_id": cpid,
                    "promotion_name": pname or "",
                    "weight_class_id": wcid,
                    "weight_class_name": wcname or "",
                    "champion_since_date": since or "",
                    "reign_length": reign,
                    "title_defenses_count": int(defs or 0),
                    "title_reigns_count": int(reigns or 0),
                    "is_player_promo": (cpid == pid),
                })
            total_champions = int(conn.execute(
                "SELECT COUNT(*) FROM titles "
                "WHERE is_vacant=0 AND current_champion_fighter_id IS NOT NULL"
            ).fetchone()[0] or 0)

            return {
                "ok": True,
                "promo": {"promotion_id": pid, "name": promo_name},
                "records": records,
                "champions": {
                    "count": total_champions,
                    "items": champions,
                },
                "sim_date": sim_date_str,
            }
        except Exception as e:
            print(f"[api.get_records_data] {e}\n{traceback.format_exc()}",
                  flush=True)
            return {"ok": False, "error": str(e),
                    "records": [],
                    "champions": {"count": 0, "items": []}}

    @staticmethod
    def _age_from_dob(dob_str, sim_date):
        """Compute a fighter's age from DOB + sim_date.

        Returns None if either date is missing or unparseable.
        """
        if not dob_str or not sim_date:
            return None
        try:
            dob = datetime.strptime(str(dob_str)[:10], "%Y-%m-%d")
            age = sim_date.year - dob.year
            if (sim_date.month, sim_date.day) < (dob.month, dob.day):
                age -= 1
            return age
        except Exception:
            return None

    # ============================================================
    # SAVE / LOAD
    # ============================================================

    def list_saves(self):
        """Return a list of available save-game names."""
        try:
            from save_load import list_saves as _list_saves
            saves = _list_saves()
            return {"saves": saves or []}
        except Exception as e:
            print(f"[api.list_saves] {e}", flush=True)
            return {"saves": [], "error": str(e)}

    def save_game(self, name):
        """Save the current game state under `name`."""
        try:
            from save_load import save_game as _save_game
            _save_game(self.conn, save_name=str(name))
            return {"ok": True, "name": str(name)}
        except Exception as e:
            print(f"[api.save_game] {e}", flush=True)
            return {"ok": False, "error": str(e)}

    def load_game(self, name):
        """Load a saved game state. Returns {ok, name}.

        P5.2 — replaces self.conn with a fresh connection to the
        restored DB. The underlying save_load.load_game() copies the
        save file over DB_PATH and returns a NEW sqlite connection
        with PRAGMA foreign_keys=ON. The old self.conn is closed
        FIRST (before the file copy) so its WAL sidecar file is
        properly released — otherwise the file copy would overwrite
        the main DB while the WAL still contains in-flight writes,
        and the loaded state could be corrupted on the next access.
        The JS side calls location.reload() after this returns so
        init() runs again and reads from the new conn.
        """
        try:
            from save_load import load_game as _load_game
            # Close the OLD conn FIRST. On Unix, closing a WAL-mode
            # sqlite conn triggers a final checkpoint that flushes
            # pending WAL writes into the main DB file + removes the
            # -wal / -shm sidecar files. If we leave the old conn
            # open, the file copy below could race with sqlite's
            # internal WAL management.
            try:
                if self.conn:
                    self.conn.close()
            except Exception as _e:
                print(f"[api.load_game] WARN: old conn close failed: {_e}",
                      flush=True)
            self.conn = None  # defensive: any concurrent API call
                              # that hits self.conn will fail loudly
                              # rather than silently use a closed conn.
            new_conn = _load_game(str(name))
            self.conn = new_conn
            # Re-apply the WAL + busy_timeout pragmas the Api init sets
            # (the new conn from save_load only sets foreign_keys=ON).
            try:
                self.conn.execute("PRAGMA journal_mode = WAL;")
                self.conn.execute("PRAGMA busy_timeout = 5000;")
            except Exception:
                pass
            return {"ok": True, "name": str(name)}
        except Exception as e:
            print(f"[api.load_game] {e}", flush=True)
            return {"ok": False, "error": str(e)}

    # ============================================================
    # CLEANUP — auto-save on window close
    # ============================================================

    def on_close(self):
        """Auto-save 'exit_save' before the window closes.

        Defensive — if the save fails, the close still proceeds. We
        never block the window close on a save failure.
        """
        try:
            if self.conn:
                try:
                    from save_load import save_game as _save_game
                    _save_game(self.conn, save_name="exit_save")
                except Exception as e:
                    print(f"[app_web] WARN: exit auto-save failed: {e}",
                          flush=True)
                self.conn.close()
        except Exception as e:
            print(f"[app_web] WARN: on_close cleanup failed: {e}",
                  flush=True)


# ============================================================
# LAUNCHER
# ============================================================

def main():
    """Create the pywebview window + run the app."""
    # Make sure the HTML file exists (defensive — clear error vs crash)
    if not INDEX_HTML.exists():
        print(f"[app_web] FATAL: index.html not found at {INDEX_HTML}",
              file=sys.stderr, flush=True)
        sys.exit(1)

    api = Api(db_path=DB_PATH)

    try:
        import webview
    except ImportError:
        print("[app_web] FATAL: pywebview is not installed.\n"
              "Install with: pip install pywebview", file=sys.stderr,
              flush=True)
        sys.exit(1)

    # Create the window — 1400x900, min 1200x800
    window = webview.create_window(
        title="CAGE EMPIRE",
        url=str(INDEX_HTML),
        js_api=api,  # pywebview 6.x: js_api STILL WORKS — the issue was elsewhere
        width=1400,
        height=900,
        min_size=(1200, 800),
        frameless=False,
        easy_drag=False,
        text_select=False,
    )

    # Wire up window close → auto-save before destroying the window.
    def _on_closing():
        try:
            api.on_close()
        except Exception as e:
            print(f"[app_web] WARN: on_closing handler failed: {e}",
                  flush=True)

    try:
        window.events.closing += _on_closing
    except Exception:
        pass

    # Start the app. http_server=True required for JS bridge on Windows.
    # debug=False — no dev console.
    try:
        webview.start(http_server=True, debug=False)
    except Exception as e:
        print(f"[app_web] FATAL: pywebview failed to start: {e}",
              file=sys.stderr, flush=True)
        # Best-effort cleanup
        try:
            api.on_close()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
