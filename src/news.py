"""CAGE EMPIRE News Engine (Task 23, extended Phase A — A4 + A5 + A6).

Template-based news generation driven by the event bus (Task 18.5).
Subscribes to FIGHT_RESOLVED, TITLE_CHANGED, TICK_ADVANCED, and 12
other event types (Phase A5) and writes rich, varied, voice-layer-
driven news items to the existing news_items table.

CONVENTIONS compliance:
  §13 — Design Law: every news item tells a story. The engine uses
        career stage, attribute descriptors, and contextual drama so
        the player remembers fights as narratives, not scorecards.
  §14 — Voice Layer: NO raw attribute values, potential numbers, or
        internal ratings appear in any player-facing news text. All
        fighter attributes are described via voice.describe_attribute
        etc. Round numbers use word forms ("first round", not
        "round 1"). Finish times use descriptive phrases ("opening
        minute", "deep into the round") instead of raw seconds.
        Career stats (wins, losses, streaks) use word forms too.
  §15 — Event Bus: the news engine is entirely event-driven. It
        subscribes to events published by resolve_next_fight and
        run_tick; no new inline side effects are added to those
        functions (§15.4). The existing write_news calls in
        app.py / tick_processor.py remain untouched — the news
        engine is ADDITIVE.

NEWS SOURCE VARIETY (A4):
  The engine picks a weighted-random news source per news item from
  the 5 sources seeded by build_db._build_fresh (System Feed, CAGE
  Wire, The Cage Wire, MMA Analytica, Social Sphere, The Pundit's
  Desk). Each source has a distinct tone — tabloids (The Cage Wire)
  prepend scandalous prefixes ("SHOCK:"), broadsheets (MMA
  Analytica) prepend analytical prefixes ("Analysis:"), etc. System
  Feed is excluded from the random pool (reserved for inline news).

EVENTS SUBSCRIBED (Phase A5):
  FIGHT_RESOLVED → generate_fight_news + generate_injury_news
  TITLE_CHANGED  → generate_title_news + generate_memory_resurfacing_news
                   (A11a — torch-passing news when new champ has a
                   'successor' memory link to a retired legend)
  TICK_ADVANCED  → generate_retirement_news (polls for newly
                   retired fighters identified by the existing
                   inline 'retirement' topic news written by
                   tick_processor._check_retirements) +
                   generate_suspension_news (Phase B — polls the
                   suspensions table for new active suspensions +
                   newly-cleared suspensions; writes creation news
                   for new suspensions and clearance news for
                   cleared ones) +
                   prune_old_news (A6 weekly pruning)
  CAMP_COMPLETED → generate_camp_news
  CAMP_INJURY    → generate_camp_injury_news
  FIGHT_CANCELLED → generate_fight_cancelled_news
  INJURY_CREATED → generate_injury_created_news
  INJURY_RECOVERED → generate_injury_recovered_news
  FIGHTER_RETIRED → generate_fighter_retired_news (career retrospective)
  FIGHTER_SIGNED → generate_fighter_signed_news
  FIGHTER_GENERATED → generate_fighter_generated_news
  CONTRACT_EXPIRED → generate_contract_expired_news
  SCOUT_REPORT_GENERATED → generate_scout_report_news
  WEIGHT_CUT_COMPLETED → generate_weight_cut_news
  EVENT_COMPLETED → generate_event_recap_news

NEWS PRUNING (A6):
  On each weekly tick (current_day % 7 == 0), news_items older than
  365 days are deleted EXCEPT for items with topic IN ('title',
  'retirement', 'hall_of_fame') which are kept forever. The prune
  is a hard DELETE (no archive table — keep it simple).

USAGE:
  from news import register_subscribers
  register_subscribers()  # call once at startup (UI / tests)

The news engine writes all items with topic='news_engine' so they
can be filtered from the existing hardcoded news (topic='fight',
'injury', 'retirement', 'training', etc.). The news_source is
selected per item from the 5 sources via _get_random_news_source.
"""

import random
from datetime import datetime

from voice import (
    describe_attribute,
    describe_career_health,
    describe_career_stage,
    describe_overall,
)


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

NEWS_TOPIC = "news_engine"
NEWS_SOURCE_NAME = "CAGE Wire"

# A4 — news source roster. Each entry: (name, credibility, sensationalism,
# bias, regional_reach, reliability, frequency). Frequency drives the
# weighted-random selection in _get_random_news_source. The seed list
# is also INSERTed into news_sources by build_db._build_fresh (so the
# fresh DB has them from the start). This list is the source of truth —
# build_db seeds it, news.py lazily re-seeds it on the world DB if any
# are missing.
_SEED_NEWS_SOURCES = [
    ("System Feed", 70, 40, 50, 60, 80, 80),
    (NEWS_SOURCE_NAME, 75, 60, 50, 70, 80, 90),
    ("The Cage Wire", 30, 80, 60, 50, 50, 70),
    ("MMA Analytica", 90, 20, 30, 80, 95, 50),
    ("Social Sphere", 50, 60, 50, 70, 60, 60),
    ("The Pundit's Desk", 60, 50, 40, 60, 70, 40),
]

# A4 — source-tone prefix per source name. Tabloids punch up headlines
# ("SHOCK:" / "SCANDAL:" / "BOMBSHELL:"); broadsheets add analytical
# framing ("Analysis:" / "In Depth:"); aggregators hedge ("Buzzing:"
# / "Trending:"); opinion desks opine ("Opinion:" / "Take:"). System
# Feed and CAGE Wire stay neutral (no prefix — they read as wire
# service copy). The prefix is added by _apply_source_tone BEFORE the
# headline so the digit-free invariant (§14) still holds.
_SOURCE_TONE_PREFIX = {
    "System Feed":        None,
    NEWS_SOURCE_NAME:     None,
    "The Cage Wire":      ("SHOCK", "SCANDAL", "BOMBSHELL", "EXCLUSIVE",
                           "CONTROVERSY"),
    "MMA Analytica":      ("Analysis", "In Depth", "By the Numbers",
                           "Strategic Breakdown", "Tactical Read"),
    "Social Sphere":      ("Buzzing", "Trending", "Going Viral",
                           "Feeds Lit", "Social Storm"),
    "The Pundit's Desk":  ("Opinion", "Take", "Hot Take", "Viewpoint",
                           "Pundit's Notebook"),
}

# Word-form maps for digit-free text (CONVENTIONS §14).
_ROUND_WORDS = {
    1: "first", 2: "second", 3: "third",
    4: "fourth", 5: "fifth",
}

_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve",
}

# All 25 attribute names — used to pick a fighter's top attributes
# for the descriptor summary. Matches the column order in
# fighter_attributes (see build_db.py).
_ATTR_NAMES = [
    "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
    "head_movement", "footwork", "clinch_striking", "clinch_offense",
    "clinch_defense", "takedown_offense", "takedown_defense",
    "top_control", "bottom_game", "submission_offense",
    "submission_defense", "scramble_ability", "cage_wrestling",
    "cardio", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "fight_iq", "chin", "adaptability",
]


# ----------------------------------------------------------------
# Digit-free phrase helpers (CONVENTIONS §14)
# ----------------------------------------------------------------

def _round_word(round_num):
    """Convert a round number to its word form ('first', 'second', ...).

    For rounds beyond the standard five, returns 'championship' (the
    championship rounds in MMA are 4 and 5, so 'late' would also
    work — but 'championship' is more evocative).
    """
    if round_num in _ROUND_WORDS:
        return _ROUND_WORDS[round_num]
    return "championship"


def _num_word(n):
    """Convert a small int to its word form for news text.

    For numbers > 12, returns a generic phrase ('over a dozen',
    'dozens of', 'numerous') so the text stays readable without
    using digit characters.
    """
    if n in _NUM_WORDS:
        return _NUM_WORDS[n]
    if n < 20:
        return "over a dozen"
    if n < 50:
        return "dozens of"
    return "numerous"


def _finish_time_phrase(finish_time_str):
    """Convert a 'M:SS' finish time string into a descriptive phrase.

    Returns phrases like 'in the opening minute', 'past the midway
    mark', 'late in the round', or 'deep into the round'. NEVER
    returns a string containing digit characters.
    """
    if not finish_time_str:
        return "during the round"
    try:
        parts = finish_time_str.split(":")
        if len(parts) != 2:
            return "during the round"
        minutes = int(parts[0])
        seconds = int(parts[1])
        total = minutes * 60 + seconds
        if total < 60:
            return "in the opening minute"
        if total < 120:
            return "past the midway mark of the round"
        if total < 180:
            return "late in the round"
        if total < 240:
            return "as the round wound down"
        return "deep into the round"
    except (ValueError, IndexError):
        return "during the round"


def _severity_phrase(severity):
    """Convert 1-10 injury severity to a descriptive phrase."""
    if severity is None:
        return "nagging"
    if severity <= 3:
        return "minor"
    if severity <= 6:
        return "moderate"
    if severity <= 8:
        return "serious"
    return "severe"


def _return_phrase(projected_return_date, current_date):
    """Convert a projected return date to a descriptive time phrase.

    Returns phrases like 'weeks on the shelf', 'months on the shelf',
    'much of the season', or 'the better part of a year'. NEVER
    returns a string containing digit characters.
    """
    if not projected_return_date or not current_date:
        return "weeks on the shelf"
    try:
        ret = datetime.strptime(projected_return_date, "%Y-%m-%d")
        cur = datetime.strptime(current_date, "%Y-%m-%d")
        days = (ret - cur).days
        if days < 30:
            return "weeks on the shelf"
        if days < 90:
            return "months on the shelf"
        if days < 180:
            return "much of the season"
        return "the better part of a year"
    except (ValueError, TypeError):
        return "weeks on the shelf"


def _result_label(result_type):
    """Return a descriptor for the fight's result type."""
    if result_type in ("ko_tko", "ko", "tko"):
        return "knockout win"
    if result_type == "submission":
        return "submission win"
    if result_type == "decision":
        return "decision win"
    if result_type == "doctor_stoppage":
        return "doctor stoppage win"
    if result_type == "draw":
        return "draw"
    if result_type == "dq":
        return "disqualification win"
    if result_type == "corner_stoppage":
        return "corner stoppage win"
    if result_type == "nc":
        return "no contest"
    return "win"


def _article_for(word):
    """Return 'an' if word starts with a vowel sound, else 'a'.

    Used to keep body templates grammatical when the next word's
    starting letter is unknown at template-authoring time (e.g.,
    career-stage descriptors from voice.py like 'active competitor'
    vs 'current titleholder'). Not perfect for unusual cases
    ('one-punch' starts with a 'w' sound but this helper returns
    'an') but covers the common cases in voice.py.
    """
    if not word:
        return "a"
    first = word[0].lower()
    if first in "aeiou":
        return "an"
    return "a"


# ----------------------------------------------------------------
# Fighter / promotion data helpers
# ----------------------------------------------------------------

def _get_news_source(conn):
    """Get or create the 'CAGE Wire' news source for news engine items.

    Distinct from 'System Feed' so the player can see at a glance
    which items came from the rich template engine (Task 23) vs.
    the legacy inline strings.
    """
    _ensure_seed_sources(conn)
    row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name=?",
        (NEWS_SOURCE_NAME,),
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO news_sources (name, credibility, sensationalism, "
        "bias, regional_reach, reliability, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (NEWS_SOURCE_NAME, 75, 60, 50, 70, 80, 90),
    ).lastrowid


def _ensure_seed_sources(conn):
    """A4 — idempotently INSERT OR IGNORE all 5 seed news sources.

    Called lazily from _get_news_source and _get_random_news_source
    so the world DB (which uses --migrate, never --fresh) gets the
    sources the first time news.py runs. On the fresh DB (which
    _build_fresh already seeds), this is a no-op.
    """
    conn.executemany(
        "INSERT OR IGNORE INTO news_sources "
        "(name, credibility, sensationalism, bias, regional_reach, "
        "reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)",
        _SEED_NEWS_SOURCES,
    )


def _get_random_news_source(conn, rng=None):
    """A4 — pick a weighted-random news source for a news item.

    Weighted by the source's `frequency` column (higher frequency =
    more likely to be picked). Ensures all 5 seed sources exist
    first (lazy idempotent INSERT). Returns the news_source_id.

    The 'System Feed' source is excluded from the random pool — it's
    reserved for inline news (app.write_news, retirement announce-
    ments, contract expiry, etc.) that should always read as "the
    official wire." The news engine's rich-template items use any of
    the other 5 sources (CAGE Wire, The Cage Wire, MMA Analytica,
    Social Sphere, The Pundit's Desk).
    """
    if rng is None:
        rng = random.Random()
    _ensure_seed_sources(conn)
    rows = conn.execute(
        "SELECT news_source_id, frequency FROM news_sources "
        "WHERE name != 'System Feed'"
    ).fetchall()
    if not rows:
        # Defensive — fall back to the CAGE Wire source.
        return _get_news_source(conn)
    weights = [(src_id, freq if freq and freq > 0 else 1)
               for src_id, freq in rows]
    total = sum(w for _, w in weights)
    roll = rng.random() * total
    cumulative = 0.0
    for src_id, w in weights:
        cumulative += w
        if roll <= cumulative:
            return src_id
    return weights[-1][0]


def _source_name(conn, src_id):
    """Return the news source name for a news_source_id (or None)."""
    if src_id is None:
        return None
    row = conn.execute(
        "SELECT name FROM news_sources WHERE news_source_id=?",
        (src_id,),
    ).fetchone()
    return row[0] if row else None


def _apply_source_tone(headline, src_name, rng=None):
    """A4 — prepend a source-flavored tag to the headline.

    Tabloids (The Cage Wire) get a scandalous prefix ("SHOCK: ...").
    Broadsheets (MMA Analytica) get an analytical prefix
    ("Analysis: ..."). Aggregators (Social Sphere) get a trending
    prefix ("Trending: ..."). Opinion desks (The Pundit's Desk) get
    an op-ed prefix ("Opinion: ..."). System Feed and CAGE Wire stay
    neutral (no prefix — wire service voice).

    The prefix is uppercase for tabloids (sensational) and title-cased
    for broadsheets/opinion (analytical). Never introduces digit
    characters (CONVENTIONS §14).
    """
    if rng is None:
        rng = random.Random()
    prefixes = _SOURCE_TONE_PREFIX.get(src_name)
    if not prefixes:
        return headline
    prefix = rng.choice(prefixes)
    # Tabloids get ALL CAPS + colon (sensational). Broadsheets/
    # aggregators/opinion get title-case + colon (analytical).
    if src_name == "The Cage Wire":
        return f"{prefix.upper()}: {headline}"
    return f"{prefix}: {headline}"


def _fighter_full_name(conn, fighter_id):
    """Return 'John Vale' or 'John "Hammer" Vale' for a fighter."""
    if fighter_id is None:
        return "Unknown Fighter"
    row = conn.execute(
        "SELECT first_name, last_name, nickname FROM fighters "
        "WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "Unknown Fighter"
    first, last, nick = row
    if nick:
        return f'{first} "{nick}" {last}'
    return f"{first} {last}"


def _fighter_last_name(conn, fighter_id):
    """Return just the fighter's last name (for headline use)."""
    if fighter_id is None:
        return "Unknown"
    row = conn.execute(
        "SELECT last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else "Unknown"


def _fighter_age(conn, fighter_id, current_date=None):
    """Compute a fighter's age based on DOB and a reference date.

    If current_date is None, falls back to the simulation_clock's
    current_date (qualified column to avoid the SQLite quirk).
    """
    row = conn.execute(
        "SELECT date_of_birth FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row or not row[0]:
        return 30  # defensive default
    dob_str = row[0]
    ref_str = current_date
    if ref_str is None:
        clock = conn.execute(
            "SELECT simulation_clock.current_date FROM simulation_clock "
            "WHERE clock_id=1"
        ).fetchone()
        ref_str = clock[0] if clock else "2026-08-15"
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d")
        ref = datetime.strptime(ref_str, "%Y-%m-%d")
        age = ref.year - dob.year
        if (ref.month, ref.day) < (dob.month, dob.day):
            age -= 1
        return age
    except (ValueError, TypeError):
        return 30


def _fighter_descriptor_summary(conn, fighter_id, rng=None):
    """Build a 2-attribute descriptor summary using the voice layer.

    Returns a phrase like "with one-punch knockout power and an
    elite chin". Picks the fighter's top 2 attributes by value and
    describes them via voice.describe_attribute. Always returns a
    non-empty phrase (falls back to "with a serviceable skill set"
    if attributes are missing).
    """
    if fighter_id is None:
        return "with an untested skill set"
    # Build the SELECT — column order must match _ATTR_NAMES exactly.
    cols_sql = ", ".join(_ATTR_NAMES)
    row = conn.execute(
        f"SELECT {cols_sql} FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "with an untested skill set"

    paired = list(zip(_ATTR_NAMES, row))
    # Sort by value descending; pick top 2 for the descriptor.
    paired.sort(key=lambda x: (x[1] if x[1] is not None else 0), reverse=True)
    top = paired[:2]

    descs = []
    for attr_name, value in top:
        if value is None:
            continue
        d = describe_attribute(attr_name, value, rng=rng)
        if d:
            descs.append(d)

    if len(descs) >= 2:
        return f"with {descs[0]} and {descs[1]}"
    if len(descs) == 1:
        return f"with {descs[0]}"
    return "with a serviceable skill set"


def _fighter_career_stage(conn, fighter_id, rng=None, current_date=None):
    """Return the fighter's career stage descriptor.

    Uses voice.describe_career_stage with the fighter's observable
    state (age, record, champion status, streaks). Does NOT reveal
    hidden potential.
    """
    if fighter_id is None:
        return "roster fighter"
    row = conn.execute(
        "SELECT fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.title_reigns, "
        "fc.career_health, "
        "EXISTS(SELECT 1 FROM titles t "
        "       WHERE t.current_champion_fighter_id = f.fighter_id) AS is_champ "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "roster fighter"
    wins, losses, draws, ws, ls, reigns, health, is_champ = row
    age = _fighter_age(conn, fighter_id, current_date=current_date)
    return describe_career_stage(
        age,
        wins or 0, losses or 0, draws or 0,
        is_champion=bool(is_champ),
        title_reigns=reigns or 0,
        win_streak=ws or 0, loss_streak=ls or 0,
        rng=rng,
    )


def _fighter_career_health(conn, fighter_id, rng=None):
    """Return the fighter's career-health descriptor (voice layer).

    Wraps voice.describe_career_health — reads fighter_career.
    career_health (0-100) and returns a phrase like "battling
    injuries" or "in peak condition". Used by the injury/retirement
    news body templates so the player gets a sense of the fighter's
    overall wear and tear (not just the specific injury being
    reported). Per CONVENTIONS §14 — no raw health numbers leak.
    """
    if fighter_id is None:
        return "in fighting shape"
    row = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row or row[0] is None:
        return "in fighting shape"
    return describe_career_health(row[0], rng=rng)


def _fighter_overall(conn, fighter_id, rng=None, current_date=None):
    """Return a one-sentence voice-layer summary of a fighter.

    Wraps voice.describe_overall — loads the fighter's career state +
    top attributes and builds a sentence like "John Vale is a striker
    with one-punch knockout threat and an excellent chin, currently a
    seasoned competitor." Used by the fight-result body templates as
    an alternate summary line so the news reads like a journalist's
    fight recap rather than a scoreboard.

    Per CONVENTIONS §14 — no raw numbers leak (voice.describe_overall
    was made digit-free in v2.10.0 / FIX-VoiceRep).
    """
    if fighter_id is None:
        return "an unprofiled fighter steps into the cage"
    row = conn.execute(
        "SELECT f.first_name, f.last_name, f.nickname, "
        "f.fight_style_archetype_id, sa.name AS style_archetype_name, "
        "fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.title_reigns, "
        "fc.career_health, "
        "EXISTS(SELECT 1 FROM titles t "
        "       WHERE t.current_champion_fighter_id = f.fighter_id) AS is_champ "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN style_archetypes sa "
        "       ON sa.style_archetype_id = f.fight_style_archetype_id "
        "WHERE f.fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "an unprofiled fighter steps into the cage"
    (first, last, nick, sa_id, sa_name,
     wins, losses, draws, ws, ls, reigns, health, is_champ) = row
    age = _fighter_age(conn, fighter_id, current_date=current_date)
    # Pull the fighter's top 2 attributes by value for the summary
    # flavor (same approach as _fighter_descriptor_summary but
    # returning a dict for voice.describe_overall's key_attributes
    # slot).
    cols_sql = ", ".join(_ATTR_NAMES)
    attr_row = conn.execute(
        f"SELECT {cols_sql} FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    key_attrs = {}
    if attr_row:
        paired = list(zip(_ATTR_NAMES, attr_row))
        paired.sort(
            key=lambda x: (x[1] if x[1] is not None else 0),
            reverse=True,
        )
        for attr_name, value in paired[:2]:
            if value is not None:
                key_attrs[attr_name] = value
    fighter_data = {
        "first_name": first or "",
        "last_name": last or "",
        "nickname": nick,
        "age": age,
        "record_wins": wins or 0,
        "record_losses": losses or 0,
        "record_draws": draws or 0,
        "is_champion": bool(is_champ),
        "title_reigns": reigns or 0,
        "win_streak": ws or 0,
        "loss_streak": ls or 0,
        "career_health": health or 100,
        "style_archetype_name": sa_name or "Balanced",
        "key_attributes": key_attrs,
    }
    return describe_overall(fighter_data, rng=rng)


def _promotion_name(conn, promo_id):
    """Return a promotion's name, or 'the promotion' as fallback."""
    if not promo_id:
        return "the promotion"
    row = conn.execute(
        "SELECT name FROM promotions WHERE promotion_id=?",
        (promo_id,),
    ).fetchone()
    return row[0] if row else "the promotion"


def _write_news_item(conn, headline, body, sentiment="neutral",
                     event_id=None, fight_id=None, fighter_id=None,
                     promotion_id=None, published_at=None, rng=None,
                     source_id=None, topic=None):
    """Write a news_engine topic news item to news_items.

    A4 — if source_id is None (the default), pick a weighted-random
    news source via _get_random_news_source. The source's tone is
    applied to the headline via _apply_source_tone (tabloids get
    "SHOCK:" prefixes, broadsheets get "Analysis:" prefixes, etc.).
    Pass source_id explicitly to bypass the random pick + tone
    (used by subscribers that have a specific source already chosen,
    e.g., the CAGE Wire for legacy consistency on certain items).

    A11a — the optional `topic` parameter (default None) lets a caller
    write the item under a different topic than NEWS_TOPIC. Used by
    the memory resurfacing subscriber (topic='memory_resurfacing')
    so future UI filters can group legacy/torch-passing news
    separately from the general 'news_engine' feed.
    """
    if rng is None:
        rng = random.Random()
    if source_id is None:
        source_id = _get_random_news_source(conn, rng=rng)
    if topic is None:
        topic = NEWS_TOPIC
    src_name = _source_name(conn, source_id)
    final_headline = _apply_source_tone(headline, src_name, rng=rng)
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, event_id, fight_id, fighter_id, "
        "promotion_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source_id, final_headline, body, sentiment, topic,
         event_id, fight_id, fighter_id, promotion_id, published_at),
    )


# ----------------------------------------------------------------
# FIGHT NEWS — subscriber for FIGHT_RESOLVED
# ----------------------------------------------------------------

# At least 3 variants per result type per the brief's "Template
# variety requirements". Each template uses {winner} / {loser} /
# {round_word} / {time_phrase} slots — no digit characters anywhere.

_FIGHT_HEADLINES_KO = [
    "{winner} lights out {loser} with devastating finish",
    "{loser}'s chin finally cracks — {winner} ends it {time_phrase}",
    "One punch was all it took — {winner} claims the finish",
    "{winner} puts {loser} away {time_phrase} — lights out",
    "{winner} starches {loser} in the {round_word} — title shot incoming",
    "Lights out for {loser} as {winner} lands the fight-ender",
]

_FIGHT_HEADLINES_SUB = [
    "{winner} taps out {loser} in the {round_word}",
    "{winner} forces the tap — {loser} has nowhere to go",
    "Submission of the night? {winner} locks in the finish",
    "{loser} caught deep — {winner} earns the submission",
    "{winner} sinks in the choke — {loser} forced to tap",
    "Tap or snap — {winner} submits {loser} {time_phrase}",
]

_FIGHT_HEADLINES_DEC = [
    "{winner} edges {loser} in close decision",
    "Judges side with {winner} in narrow one",
    "{winner} takes it on the cards — {loser} left wanting",
    "All three judges see it for {winner} — {loser} falls short",
    "{winner} outpoints {loser} in tactical battle",
    "Scorecards favor {winner} — {loser} rallies but falls short",
]

_FIGHT_HEADLINES_DRAW = [
    "{a} and {b} fight to a stalemate",
    "No winner — {a} and {b} split the judges",
    "Dead even — {a} vs {b} ends in a draw",
    "{a} and {b} leave it all in the cage — draw",
]

_FIGHT_HEADLINES_DOCTOR = [
    "Doctor waves it off — {winner} defeats {loser}",
    "{loser} can't continue — {winner} wins by stoppage",
    "Ringside physician halts the bout — {winner} takes the win",
]

_FIGHT_HEADLINES_OTHER = [
    "{winner} defeats {loser} in the {round_word}",
    "{winner} gets the win over {loser}",
    "{winner} handles {loser} {time_phrase}",
]

# Body templates include voice descriptors (career_stage + attr_summary)
# plus contextual detail (promotion, result_label, time_phrase). At
# least 3 variants per the brief. The {winner_art} / {loser_art}
# slots are filled with "a" or "an" based on the career-stage word
# so the text reads grammatically regardless of which stage voice.py
# returns.
#
# v2.10.0 (FIX-VoiceRep, §14): two new templates added that use
# {winner_overall} — a one-sentence voice.describe_overall summary
# of the winner ("John Vale is a striker with one-punch knockout
# threat and an excellent chin, currently a seasoned competitor").
# This closes the §14 violation where the news engine wasn't using
# voice.describe_overall (one of the 4 required voice functions per
# the brief). The summary is digit-free (voice.describe_overall was
# made digit-free in v2.10.0).
_FIGHT_BODY_TEMPLATES = [
    "{winner_full}, {winner_art} {career_stage}, {attr_summary}, earns the "
    "{result_label} over {loser_full} {time_phrase} of the {round_word} "
    "round. The {promotion_name} tilt validates {winner_last}'s "
    "standing in the division.",

    "{winner_full} {attr_summary} proves the difference as {loser_full} "
    "({loser_art} {loser_stage}) falters under pressure. The {result_label_cap} "
    "in the {round_word} round leaves {loser_last} searching for answers.",

    "In a fight that {promotion_name} will remember, {winner_full} "
    "({winner_art} {career_stage}) {attr_summary} dismantles {loser_full} "
    "{time_phrase}. {loser_last} ({loser_art} {loser_stage}) never finds their rhythm.",

    "{winner_full}, {winner_art} {career_stage}, {attr_summary}, claims the "
    "{result_label} over {loser_full} {time_phrase}. The {promotion_name} "
    "crowd watches {loser_last} ({loser_art} {loser_stage}) come up short.",

    "{winner_overall}. That line writes itself after {winner_last} "
    "({winner_art} {career_stage}) {attr_summary} claims the {result_label} "
    "over {loser_full} ({loser_art} {loser_stage}) {time_phrase} of the "
    "{round_word} round — a {promotion_name} result that reshuffles the "
    "division.",

    "The {promotion_name} cage sees {winner_full} ({winner_art} {career_stage}) "
    "{attr_summary} take the {result_label} over {loser_full} {time_phrase}. "
    "{winner_overall}. {loser_last} ({loser_art} {loser_stage}) is left "
    "searching for answers in the aftermath.",
]


def generate_fight_news(conn, event):
    """Subscriber for FIGHT_RESOLVED — generates varied fight result news.

    Picks a headline template based on result_type, fills slots with
    fighter names, voice descriptors, round/time context, and writes
    a news_engine item. Uses a fresh RNG per call for variety (the
    test case B variety check verifies at least three distinct
    headlines over multiple calls).
    """
    fight_id = event.get("fight_id")
    winner_id = event.get("winner_id")
    loser_id = event.get("loser_id")
    result_type = event.get("result_type", "") or ""
    finish_round = event.get("finish_round") or 1
    finish_time = event.get("finish_time", "") or ""
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    event_date = event.get("event_date")
    is_title = event.get("is_title_fight", False)
    a_id = event.get("fighter_a_id")
    b_id = event.get("fighter_b_id")

    rng = random.Random()  # fresh RNG per call for variety

    # ---- DRAW branch ----
    # winner_id and loser_id are None for draws; use a_id and b_id.
    if result_type == "draw" or winner_id is None or loser_id is None:
        if a_id is None or b_id is None:
            return  # not enough context to write news
        a_last = _fighter_last_name(conn, a_id)
        b_last = _fighter_last_name(conn, b_id)
        headline = rng.choice(_FIGHT_HEADLINES_DRAW).format(
            a=a_last, b=b_last,
        )
        body = (
            f"{_fighter_full_name(conn, a_id)} and "
            f"{_fighter_full_name(conn, b_id)} trade blows through the "
            f"scheduled rounds but the judges cannot split them. The "
            f"draw leaves both fighters searching for answers in the "
            f"{_promotion_name(conn, promo_id)} division."
        )
        news_fighter_id = a_id
        sentiment = "neutral"
    else:
        # ---- WINNER / LOSER branch ----
        winner_last = _fighter_last_name(conn, winner_id)
        loser_last = _fighter_last_name(conn, loser_id)
        winner_full = _fighter_full_name(conn, winner_id)
        loser_full = _fighter_full_name(conn, loser_id)
        round_word = _round_word(finish_round)
        time_phrase = _finish_time_phrase(finish_time)
        career_stage = _fighter_career_stage(
            conn, winner_id, rng=rng, current_date=event_date,
        )
        loser_stage = _fighter_career_stage(
            conn, loser_id, rng=rng, current_date=event_date,
        )
        attr_summary = _fighter_descriptor_summary(conn, winner_id, rng=rng)
        # v2.10.0 (FIX-VoiceRep): one-sentence voice.describe_overall
        # summary of the winner — used by the {winner_overall} body
        # template slots. Closes the §14 violation where the news
        # engine didn't use voice.describe_overall (one of the 4
        # required voice functions per the brief).
        winner_overall = _fighter_overall(
            conn, winner_id, rng=rng, current_date=event_date,
        )
        result_label = _result_label(result_type)
        result_label_cap = result_label.capitalize()
        promotion_name = _promotion_name(conn, promo_id)

        # Pick headline pool based on result_type.
        rt = result_type.lower()
        if rt in ("ko_tko", "ko", "tko"):
            head_templates = _FIGHT_HEADLINES_KO
        elif rt == "submission":
            head_templates = _FIGHT_HEADLINES_SUB
        elif rt == "decision":
            head_templates = _FIGHT_HEADLINES_DEC
        elif rt == "doctor_stoppage":
            head_templates = _FIGHT_HEADLINES_DOCTOR
        else:
            head_templates = _FIGHT_HEADLINES_OTHER

        headline = rng.choice(head_templates).format(
            winner=winner_last, loser=loser_last,
            round_word=round_word, time_phrase=time_phrase,
        )

        body = rng.choice(_FIGHT_BODY_TEMPLATES).format(
            winner_full=winner_full, loser_full=loser_full,
            winner_last=winner_last, loser_last=loser_last,
            career_stage=career_stage, loser_stage=loser_stage,
            winner_art=_article_for(career_stage),
            loser_art=_article_for(loser_stage),
            attr_summary=attr_summary, round_word=round_word,
            time_phrase=time_phrase, result_label=result_label,
            result_label_cap=result_label_cap,
            promotion_name=promotion_name,
            winner_overall=winner_overall,
        )
        news_fighter_id = winner_id
        sentiment = "positive"

    # Append title-fight context if applicable (no numbers — uses
    # word forms only).
    if is_title:
        body += " Title-fight implications will echo through the division."

    _write_news_item(
        conn, headline, body, sentiment=sentiment,
        event_id=event_id, fight_id=fight_id,
        fighter_id=news_fighter_id, promotion_id=promo_id,
        published_at=event_date,
    )


# ----------------------------------------------------------------
# TITLE NEWS — subscriber for TITLE_CHANGED
# ----------------------------------------------------------------

_TITLE_HEADLINES_NEW_CHAMP = [
    "NEW CHAMPION — {winner} dethrones {loser} for the title",
    "The reign is over — {winner} claims the belt",
    "Title changes hands — {winner} takes the crown",
    "{winner} captures gold — {loser} left in the rearview",
    "New king crowned — {winner} seizes the throne",
]

_TITLE_HEADLINES_VACANT = [
    "NEW CHAMPION — {winner} claims the vacant title",
    "{winner} ascends — vacant title finds a new home",
    "The throne was empty — {winner} fills it",
    "{winner} captures the vacant crown",
    "Vacant no more — {winner} seizes the belt",
]

_TITLE_BODY_TEMPLATES = [
    "{winner_full}, {winner_art} {career_stage}, {attr_summary}, stands atop the "
    "division after dispatching {loser_full} ({loser_art} {loser_stage}). The "
    "{promotion_name} title fight delivers a moment that will echo "
    "through the division for years.",

    "Gold changes hands. {winner_full}, {winner_art} {career_stage}, "
    "{attr_summary}, dethrones {loser_full} ({loser_art} {loser_stage}) in a "
    "fight that defines the {promotion_name} landscape. A new era begins.",

    "{winner_full} ({winner_art} {career_stage}) {attr_summary} seizes the title "
    "from {loser_full} ({loser_art} {loser_stage}). The {promotion_name} crown "
    "has a new owner — and the division may never be the same.",
]

_TITLE_BODY_TEMPLATES_VACANT = [
    "{winner_full}, {winner_art} {career_stage}, {attr_summary}, ascends to the "
    "throne as the {promotion_name} title finds its first champion. "
    "The vacant reign is over — a new era begins.",

    "Gold finds a home. {winner_full}, {winner_art} {career_stage}, "
    "{attr_summary}, claims the vacant {promotion_name} title. The "
    "division has its champion — and the contenders are already "
    "lining up.",

    "{winner_full} ({winner_art} {career_stage}) {attr_summary} seizes the vacant "
    "{promotion_name} crown. The throne is no longer empty — and the "
    "division's hierarchy resets around its new king.",
]


def generate_title_news(conn, event):
    """Subscriber for TITLE_CHANGED — generates title change news.

    Distinguishes between 'vacant title claimed' (first-ever reign
    for the title) and 'reigning champion dethroned'. Uses the
    title_reigns_count to detect the vacant case: if reigns_count
    equals one, this is the inaugural reign (the title was vacant).
    If greater than one, a champion was dethroned.
    """
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")

    if not title_id or not fight_id:
        return

    rng = random.Random()

    title_row = conn.execute(
        "SELECT current_champion_fighter_id, champion_since_date, "
        "title_reigns_count, is_vacant FROM titles WHERE title_id=?",
        (title_id,),
    ).fetchone()
    if not title_row:
        return
    champ_id, since_date, reigns_count, _is_vacant_now = title_row
    if not champ_id:
        return  # title is currently vacant — nothing to report

    fight_row = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type, "
        "finish_round, finish_time FROM fights WHERE fight_id=?",
        (fight_id,),
    ).fetchone()
    if not fight_row:
        return
    winner_id, loser_id, _rt, _fr, _ft = fight_row
    if winner_id != champ_id:
        # Defensive: title says champ is X, fight says winner is Y.
        # The title row is authoritative (it was just updated).
        winner_id = champ_id

    # Vacant claim vs. dethroning: reigns_count == 1 means this is
    # the title's first reign (was vacant, now claimed). reigns_count
    # > 1 means a champion was dethroned.
    is_vacant_claim = (reigns_count is None or reigns_count == 1)

    winner_full = _fighter_full_name(conn, winner_id)
    winner_last = _fighter_last_name(conn, winner_id)
    career_stage = _fighter_career_stage(
        conn, winner_id, rng=rng, current_date=since_date,
    )
    attr_summary = _fighter_descriptor_summary(conn, winner_id, rng=rng)
    promotion_name = _promotion_name(conn, promo_id)

    if is_vacant_claim:
        headline = rng.choice(_TITLE_HEADLINES_VACANT).format(
            winner=winner_last,
        )
        body = rng.choice(_TITLE_BODY_TEMPLATES_VACANT).format(
            winner_full=winner_full, career_stage=career_stage,
            winner_art=_article_for(career_stage),
            attr_summary=attr_summary, promotion_name=promotion_name,
        )
    else:
        # Dethroning — use the loser (former champion) for context.
        if loser_id is None:
            loser_full = "the previous champion"
            loser_stage = "former titleholder"
            loser_last = "the former champ"
        else:
            loser_full = _fighter_full_name(conn, loser_id)
            loser_stage = _fighter_career_stage(
                conn, loser_id, rng=rng, current_date=since_date,
            )
            loser_last = _fighter_last_name(conn, loser_id)
        headline = rng.choice(_TITLE_HEADLINES_NEW_CHAMP).format(
            winner=winner_last, loser=loser_last,
        )
        body = rng.choice(_TITLE_BODY_TEMPLATES).format(
            winner_full=winner_full, career_stage=career_stage,
            winner_art=_article_for(career_stage),
            attr_summary=attr_summary,
            loser_full=loser_full, loser_stage=loser_stage,
            loser_art=_article_for(loser_stage),
            promotion_name=promotion_name,
        )

    _write_news_item(
        conn, headline, body, sentiment="positive",
        event_id=event_id, fight_id=fight_id, fighter_id=winner_id,
        promotion_id=promo_id, published_at=since_date,
    )


# ----------------------------------------------------------------
# MEMORY RESURFACING NEWS — A11a subscriber for TITLE_CHANGED
#
# When a new champion is crowned, the engine checks the
# `fighter_memory_links` table for a 'successor' link on the new
# champion's fighter_id. The regen system (tick_processor.
# _check_retirements) writes these rows when a retiring champion
# spawns a regen replacement — the replacement inherits the
# retiring fighter's style archetype and gets a memory link
# pointing back to the legend. Before A11a, that link was written
# but NEVER read. This subscriber closes the loop: when the
# successor wins a title of their own, the news engine tells the
# story ("the torch passes", "echoes of the legend", "honors the
# memory"). This is the Legacy pillar of the Design Law (§13) —
# the world remembers what the player built.
#
# The news item is ADDITIONAL to generate_title_news (the standard
# title change writeup). It uses topic='memory_resurfacing' so
# future UI filters can group legacy/torch-passing stories
# separately. The item is kept indefinitely by the A6 pruner
# (added to _NEWS_PRUNE_KEEP_TOPICS) — memory stories are the
# kind of long-tail content the player collects.
# ----------------------------------------------------------------

_MEMORY_HEADLINES = [
    "The torch passes — {new_champ} carries the legacy of {legend}",
    "Fans see echoes of {legend} in {new_champ}'s style",
    "{new_champ} honors the memory of {legend} with the title win",
    "A new chapter for an old story — {new_champ} channels {legend}",
    "Echoes of the past — {new_champ} takes the throne {legend} once held",
]

_MEMORY_BODY_TEMPLATES = [
    "{new_champ_full}, {new_champ_art} {new_champ_stage}, ascends to the "
    "title — and fight fans can't help but remember {legend_full} "
    "({legend_art} {legend_stage}). The echoes are unmistakable: the "
    "same approach, the same killer instinct, a style passed down like "
    "an heirloom. The legacy lives on.",

    "Gold finds a familiar home. {new_champ_full}, {new_champ_art} "
    "{new_champ_stage}, captures the title — and the comparisons to "
    "{legend_full} ({legend_art} {legend_stage}) write themselves. "
    "The sport has a long memory, and tonight it whispers a name from "
    "a different era.",

    "The crown passes, the memory endures. {new_champ_full} "
    "({new_champ_art} {new_champ_stage}) honors {legend_full} "
    "({legend_art} {legend_stage}) with the title win — a stylistic "
    "succession that the old champion would have recognized and "
    "respected. The torch has been passed.",

    "{new_champ_full} ({new_champ_art} {new_champ_stage}) steps into "
    "the role {legend_full} ({legend_art} {legend_stage}) once owned. "
    "The title belt may be new in their hands, but the style, the "
    "instincts, the very DNA of the approach — all of it recalls a "
    "legend whose name still echoes through the division.",
]


def generate_memory_resurfacing_news(conn, event):
    """Subscriber for TITLE_CHANGED — A11a memory resurfacing.

    When a new champion is crowned, check `fighter_memory_links` for
    a 'successor' link on the new champion. If one exists, the new
    champion is the regen replacement of a retired legend — write a
    memory resurfacing news item that tells the torch-passing story.

    The item is ADDITIONAL to generate_title_news (which already
    wrote the standard title change writeup). Uses
    topic='memory_resurfacing' and a random news source (per A4).
    """
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")

    if not title_id or not fight_id:
        return

    title_row = conn.execute(
        "SELECT current_champion_fighter_id, champion_since_date "
        "FROM titles WHERE title_id=?",
        (title_id,),
    ).fetchone()
    if not title_row:
        return
    new_champ_id, since_date = title_row
    if not new_champ_id:
        return  # title is currently vacant — nothing to resurface

    # Look for a 'successor' link on the new champion. The regen
    # system writes these rows with fighter_id=replacement and
    # linked_fighter_id=retiring_champion. We only care about
    # 'successor' links — other link_types (style_echo, gym_heir,
    # regional_rival) are not torch-passing moments and don't get
    # the memory resurfacing news on a title win.
    link_row = conn.execute(
        "SELECT linked_fighter_id, link_strength "
        "FROM fighter_memory_links "
        "WHERE fighter_id=? AND link_type='successor' "
        "LIMIT 1",
        (new_champ_id,),
    ).fetchone()
    if not link_row:
        return  # the new champion has no predecessor — no memory story
    legend_id, _link_strength = link_row

    # Defensive: don't resurface memory if the legend is the same as
    # the new champ (shouldn't happen — successor links always point
    # at a different fighter — but the UNIQUE constraint allows it).
    if legend_id == new_champ_id:
        return

    rng = random.Random()

    new_champ_full = _fighter_full_name(conn, new_champ_id)
    new_champ_last = _fighter_last_name(conn, new_champ_id)
    new_champ_stage = _fighter_career_stage(
        conn, new_champ_id, rng=rng, current_date=since_date,
    )
    legend_full = _fighter_full_name(conn, legend_id)
    legend_last = _fighter_last_name(conn, legend_id)
    legend_stage = _fighter_career_stage(
        conn, legend_id, rng=rng, current_date=since_date,
    )

    headline = rng.choice(_MEMORY_HEADLINES).format(
        new_champ=new_champ_last, legend=legend_last,
    )
    body = rng.choice(_MEMORY_BODY_TEMPLATES).format(
        new_champ_full=new_champ_full,
        new_champ_art=_article_for(new_champ_stage),
        new_champ_stage=new_champ_stage,
        legend_full=legend_full,
        legend_art=_article_for(legend_stage),
        legend_stage=legend_stage,
    )

    _write_news_item(
        conn, headline, body, sentiment="positive",
        event_id=event_id, fight_id=fight_id, fighter_id=new_champ_id,
        promotion_id=promo_id, published_at=since_date,
        rng=rng, topic="memory_resurfacing",
    )


# ----------------------------------------------------------------
# INJURY NEWS — subscriber for FIGHT_RESOLVED
# ----------------------------------------------------------------

_INJURY_HEADLINES = [
    "{fighter} sidelined with {injury}",
    "Recovery timeline set for {fighter}'s {injury}",
    "{fighter} faces the sidelines after fight injury",
    "{fighter} goes down — {injury} confirmed",
    "{fighter} nursing {injury} after the bout",
]

_INJURY_BODY_TEMPLATES = [
    "{fighter_full}, {art} {career_stage}, {attr_summary}, suffers {injury} "
    "during the bout. Projected return: {return_phrase}. The road back "
    "begins now for {fighter_last}.",

    "{fighter_full} ({art} {career_stage}) goes down with {injury} — "
    "{return_phrase} on the shelf. The {attr_summary} that defined "
    "their run will be tested in the comeback.",

    "Bad news for {fighter_full}: {injury}. The {career_stage} faces "
    "{return_phrase} before they can compete again. {fighter_last}'s "
    "future hangs in the balance.",

    # v2.10.0 (FIX-VoiceRep): new template using {health_state} —
    # voice.describe_career_health descriptor ("battling injuries",
    # "worn down", "in peak condition"). Closes the §14 violation
    # where the news engine didn't use voice.describe_career_health
    # (one of the 4 required voice functions per the brief).
    "{fighter_full}, {art} {career_stage} already {health_state}, "
    "now faces {injury} on top of the wear and tear. {return_phrase} "
    "on the shelf — the {attr_summary} that defined {fighter_last}'s "
    "run will be tested in the comeback.",
]


def generate_injury_news(conn, event):
    """Subscriber for FIGHT_RESOLVED — generates injury news.

    Scans the injuries table for any injuries tied to the fight_id
    and writes a news_engine item per injury. Uses voice descriptors
    for the injured fighter's career stage and attributes; describes
    severity and projected return time without raw numbers.
    """
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    event_date = event.get("event_date")

    if not fight_id:
        return

    injuries = conn.execute(
        "SELECT injury_id, fighter_id, injury_type, severity, "
        "body_area, projected_return_date "
        "FROM injuries WHERE fight_id=?",
        (fight_id,),
    ).fetchall()
    if not injuries:
        return  # no injuries tied to this fight

    rng = random.Random()

    for (injury_id, fighter_id, injury_type, severity,
         body_area, projected_return_date) in injuries:
        # Dedup: skip if a news_engine item already exists for this
        # fighter + injury_type on this fight. (Defensive — the bus
        # only fires once per fight, but a future re-publish path
        # could fire twice.)
        existing = conn.execute(
            "SELECT 1 FROM news_items WHERE topic=? "
            "AND fight_id=? AND fighter_id=? "
            "AND headline LIKE ?",
            (NEWS_TOPIC, fight_id, fighter_id, f"%{injury_type}%"),
        ).fetchone()
        if existing:
            continue

        fighter_full = _fighter_full_name(conn, fighter_id)
        fighter_last = _fighter_last_name(conn, fighter_id)
        career_stage = _fighter_career_stage(
            conn, fighter_id, rng=rng, current_date=event_date,
        )
        attr_summary = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
        # v2.10.0 (FIX-VoiceRep): voice.describe_career_health
        # descriptor for the {health_state} body template slot —
        # phrases like "battling injuries" or "worn down" give the
        # player a sense of the fighter's overall wear and tear
        # (not just the specific injury being reported). §14 — no
        # raw health numbers leak.
        health_state = _fighter_career_health(conn, fighter_id, rng=rng)
        sev_phrase = _severity_phrase(severity)
        ret_phrase = _return_phrase(projected_return_date, event_date)

        # Build an injury noun phrase. injury_type is a free-form
        # string from the injuries table (e.g., "torn ACL",
        # "broken hand", "concussion"). Severity prefix is a voice
        # descriptor — no raw numbers.
        injury_phrase = f"a {sev_phrase} {injury_type}"

        headline = rng.choice(_INJURY_HEADLINES).format(
            fighter=fighter_last, injury=injury_phrase,
        )
        body = rng.choice(_INJURY_BODY_TEMPLATES).format(
            fighter_full=fighter_full, fighter_last=fighter_last,
            career_stage=career_stage, art=_article_for(career_stage),
            attr_summary=attr_summary, health_state=health_state,
            injury=injury_phrase, return_phrase=ret_phrase,
        )

        _write_news_item(
            conn, headline, body, sentiment="negative",
            event_id=event_id, fight_id=fight_id, fighter_id=fighter_id,
            promotion_id=promo_id, published_at=event_date,
        )


# ----------------------------------------------------------------
# RETIREMENT NEWS — subscriber for TICK_ADVANCED
# ----------------------------------------------------------------

_RETIREMENT_HEADLINES = [
    "{fighter} hangs them up",
    "End of an era — {fighter} announces retirement",
    "{fighter} walks away from the cage",
    "The career is over — {fighter} retires",
    "{fighter} calls it a career",
]

_RETIREMENT_BODY_TEMPLATES = [
    "{fighter_full}, {art} {career_stage}, {attr_summary}, announces "
    "retirement from professional MMA. {reign_phrase} {fighter_last} "
    "{legacy_phrase}. The {promotion_name} roster loses a competitor "
    "who left it all inside.",

    "After a career that spanned the {promotion_name} landscape, "
    "{fighter_full} ({art} {career_stage}) {attr_summary} walks away. "
    "{reign_phrase} {fighter_last} {legacy_phrase}.",

    "{fighter_full} ({art} {career_stage}) {attr_summary} calls it a "
    "career. {reign_phrase} {fighter_last} {legacy_phrase}. The cage "
    "loses a fighter who left it all inside.",

    # v2.10.0 (FIX-VoiceRep): new template using {health_state} —
    # voice.describe_career_health descriptor. Retirement is the
    # natural place to describe the fighter's overall wear and tear
    # ("physically broken", "should retire", "battling injuries").
    # Closes the §14 violation where the news engine didn't use
    # voice.describe_career_health in retirement news.
    "{fighter_full}, {art} {career_stage} now {health_state}, calls "
    "it a career. {reign_phrase} {fighter_last} {legacy_phrase}. The "
    "{promotion_name} roster loses a competitor who left it all inside.",
]

_LEGACY_PHRASES = [
    "leaves behind a record of {wins} wins, {losses} losses, and a draw",
    "departs with {wins} wins and {losses} losses on the resume",
    "compiled {wins} career wins against {losses} defeats",
    "exits with {wins} victories to their name",
]


def generate_retirement_news(conn, event):
    """Subscriber for TICK_ADVANCED — polls for newly retired fighters.

    The existing tick_processor._check_retirements function writes a
    'retirement' topic news item (inline, with fighter_id set) when
    a fighter retires. This subscriber fires on every TICK_ADVANCED
    and polls for those 'retirement' topic items published today.
    For each, if no news_engine retirement item exists for that
    fighter yet, write one with rich, voice-layer-driven detail.

    This polling pattern is used because no FIGHTER_RETIRED event
    is currently published on the bus (the existing inline code path
    handles retirement directly). A future task could publish
    FIGHTER_RETIRED and this subscriber could migrate to it.
    """
    current_date = event.get("current_date")
    if not current_date:
        return

    retirements_today = conn.execute(
        "SELECT fighter_id FROM news_items "
        "WHERE topic='retirement' AND published_at=? "
        "AND fighter_id IS NOT NULL",
        (current_date,),
    ).fetchall()
    if not retirements_today:
        return

    rng = random.Random()

    for (fighter_id,) in retirements_today:
        # Dedup: skip if we've already written a news_engine
        # retirement item for this fighter (headline contains a
        # retirement keyword).
        existing = conn.execute(
            "SELECT 1 FROM news_items WHERE topic=? AND fighter_id=? "
            "AND (headline LIKE '%hangs them up%' "
            "OR headline LIKE '%retire%' "
            "OR headline LIKE '%walks away%' "
            "OR headline LIKE '%calls it a career%')",
            (NEWS_TOPIC, fighter_id),
        ).fetchone()
        if existing:
            continue

        fighter_full = _fighter_full_name(conn, fighter_id)
        fighter_last = _fighter_last_name(conn, fighter_id)
        career_stage = _fighter_career_stage(
            conn, fighter_id, rng=rng, current_date=current_date,
        )
        attr_summary = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
        # v2.10.0 (FIX-VoiceRep): voice.describe_career_health
        # descriptor for the {health_state} body template slot.
        health_state = _fighter_career_health(conn, fighter_id, rng=rng)

        # Career stats for the legacy phrase. Word-form numbers (no
        # digit characters per CONVENTIONS §14).
        career_row = conn.execute(
            "SELECT record_wins, record_losses, record_draws, "
            "title_reigns, career_health "
            "FROM fighter_career WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        if career_row:
            wins, losses, draws, reigns, health = career_row
            wins_word = _num_word(wins or 0)
            losses_word = _num_word(losses or 0)
            reigns = reigns or 0
        else:
            wins_word = "several"
            losses_word = "several"
            reigns = 0

        if reigns > 0:
            reigns_word = _num_word(reigns)
            reign_phrase = f"A {reigns_word}-time champion,"
        else:
            reign_phrase = "A respected competitor,"

        legacy_phrase = rng.choice(_LEGACY_PHRASES).format(
            wins=wins_word, losses=losses_word,
        )

        # Find the fighter's last promotion (for the promotion_name
        # context). current_promotion_id may be NULL if they were a
        # free agent at retirement, in which case we use a generic.
        promo_row = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        promo_id = promo_row[0] if promo_row else None
        promotion_name = _promotion_name(conn, promo_id)

        headline = rng.choice(_RETIREMENT_HEADLINES).format(
            fighter=fighter_last,
        )
        body = rng.choice(_RETIREMENT_BODY_TEMPLATES).format(
            fighter_full=fighter_full, fighter_last=fighter_last,
            career_stage=career_stage,
            art=_article_for(career_stage),
            attr_summary=attr_summary, reign_phrase=reign_phrase,
            legacy_phrase=legacy_phrase, health_state=health_state,
            promotion_name=promotion_name,
        )

        _write_news_item(
            conn, headline, body, sentiment="neutral",
            fighter_id=fighter_id, promotion_id=promo_id,
            published_at=current_date,
        )


# ----------------------------------------------------------------
# A5 — subscribers for the previously-unsubscribed event types.
# Each subscriber writes a single news_engine item per event with a
# short, voice-layer-driven headline + body. The subscribers are
# defensive — missing fields in the event dict cause a silent return
# (no crash). The body uses career-stage + attribute descriptors
# from voice.py (no raw numbers per §14).
# ----------------------------------------------------------------

# Shared headline pools per topic (at least 3 variants each for
# variety — the test verifies at least 3 distinct headlines over
# multiple calls).

_CAMP_COMPLETED_HEADLINES = [
    "{fighter} wraps training camp",
    "Camp in the books for {fighter}",
    "{fighter} finishes camp — ready for the cage",
    "Training camp complete for {fighter}",
]

_CAMP_INJURY_HEADLINES = [
    "{fighter} suffers training injury",
    "Camp derailed — {fighter} goes down",
    "{fighter} injured in training",
    "Setback in camp for {fighter}",
]

_FIGHT_CANCELLED_HEADLINES = [
    "Fight cancelled — {fighter} misses weight",
    "Weight cut claims another fight — {fighter} off the card",
    "{fighter} misses weight; bout scrapped",
    "Scale claims {fighter} — fight cancelled",
]

_INJURY_RECOVERED_HEADLINES = [
    "{fighter} cleared to return",
    "{fighter} back from injury",
    "Medical clearance for {fighter}",
    "{fighter} returns to active duty",
]

_FIGHTER_SIGNED_HEADLINES = [
    "{fighter} signs with {promotion}",
    "{promotion} inks {fighter}",
    "{fighter} joins {promotion} roster",
    "New deal — {fighter} signs with {promotion}",
]

_FIGHTER_GENERATED_HEADLINES = [
    "New prospect {fighter} emerges",
    "{fighter} arrives on the scene",
    "Fresh face — {fighter} debuts",
    "Scouts take note of {fighter}",
]

_CONTRACT_EXPIRED_HEADLINES = [
    "{fighter}'s contract expires — free agency beckons",
    "{fighter} hits the open market",
    "{fighter} becomes a free agent",
    "Contract up — {fighter} unsigned",
]

_SCOUT_REPORT_HEADLINES = [
    "Scout report filed on {fighter}",
    "Scouting notebook: {fighter}",
    "{fighter} under the scout's microscope",
    "New scouting report — {fighter}",
]

_WEIGHT_CUT_HEADLINES = [
    "Weigh-in results — {fighter} hits the mark",
    "{fighter} makes weight",
    "Scale watch — {fighter} on weight",
    "{fighter} completes the cut",
]

_EVENT_RECAP_HEADLINES = [
    "{promotion} event recap",
    "Card in the books — {promotion} recap",
    "{promotion} event wraps",
    "Recap: {promotion} latest card",
]


def _short_descriptor_summary(conn, fighter_id, rng=None):
    """Return a single-attribute descriptor summary (lighter than the
    2-attribute _fighter_descriptor_summary). Used by the A5 short news
    items so they don't all read identically. Falls back to a generic
    phrase if the fighter has no attributes row.
    """
    if rng is None:
        rng = random.Random()
    desc = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
    return desc or "with a serviceable skill set"


def generate_camp_news(conn, event):
    """A5 — subscriber for CAMP_COMPLETED.

    Writes a short news_engine item announcing the fighter finished
    their training camp. Uses career stage + a single attribute
    descriptor in the body (no raw numbers per §14).
    """
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(conn, fighter_id, rng=rng)
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    headline = rng.choice(_CAMP_COMPLETED_HEADLINES).format(
        fighter=fighter_last,
    )
    body = (
        f"{fighter_full}, {_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}, has wrapped training camp and is ready for "
        f"their next outing. The work is done — now it's about "
        f"executing on fight night."
    )
    _write_news_item(
        conn, headline, body, sentiment="positive",
        fighter_id=fighter_id, rng=rng,
        published_at=event.get("current_date"),
    )


def generate_camp_injury_news(conn, event):
    """A5 — subscriber for CAMP_INJURY."""
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(conn, fighter_id, rng=rng)
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    headline = rng.choice(_CAMP_INJURY_HEADLINES).format(
        fighter=fighter_last,
    )
    body = (
        f"Bad news out of camp — {fighter_full}, "
        f"{_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}, has suffered a training injury. The setback "
        f"disrupts their preparation; a return timeline will follow "
        f"once the medical team evaluates the damage."
    )
    _write_news_item(
        conn, headline, body, sentiment="negative",
        fighter_id=fighter_id, rng=rng,
        published_at=event.get("current_date"),
    )


def generate_fight_cancelled_news(conn, event):
    """A5 — subscriber for FIGHT_CANCELLED.

    Published by app.py's weight cut cancellation path. The event
    payload includes missed_fighter_id (the fighter who missed weight)
    and opponent_id (the fighter who made weight). Both get a news
    mention — the offender for missing weight, the opponent for the
    bad luck of losing their fight.
    """
    missed_id = event.get("missed_fighter_id")
    opponent_id = event.get("opponent_id")
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    event_date = event.get("event_date")
    if missed_id is None:
        return
    rng = random.Random()
    missed_full = _fighter_full_name(conn, missed_id)
    missed_last = _fighter_last_name(conn, missed_id)
    career_stage = _fighter_career_stage(
        conn, missed_id, rng=rng, current_date=event_date,
    )
    attr_summary = _short_descriptor_summary(conn, missed_id, rng=rng)
    headline = rng.choice(_FIGHT_CANCELLED_HEADLINES).format(
        fighter=missed_last,
    )
    body = (
        f"The bout has been cancelled after {missed_full}, "
        f"{_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}, missed weight. "
    )
    if opponent_id is not None:
        opp_full = _fighter_full_name(conn, opponent_id)
        body += (
            f"{opp_full} loses their spot on the card through no "
            f"fault of their own — the sport can be cruel that way."
        )
    else:
        body += "No opponent was named for the reshuffle."
    _write_news_item(
        conn, headline, body, sentiment="negative",
        event_id=event_id, fight_id=fight_id, fighter_id=missed_id,
        promotion_id=promo_id, published_at=event_date, rng=rng,
    )


def generate_injury_created_news(conn, event):
    """A5 — subscriber for INJURY_CREATED.

    The event payload includes injury_id (or fight_id + fighter_id).
    Looks up the injury row to extract type/severity/return date and
    writes a news item. Mirrors generate_injury_news (which is fired
    by FIGHT_RESOLVED) but is fired by the explicit INJURY_CREATED
    event so non-fight injuries (training camp injuries, etc.) also
    get coverage.
    """
    injury_id = event.get("injury_id")
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    event_date = event.get("event_date") or event.get("current_date")
    fighter_id = event.get("fighter_id")
    # If injury_id is provided, look up the injury row.
    if injury_id is not None:
        row = conn.execute(
            "SELECT fighter_id, injury_type, severity, body_area, "
            "projected_return_date FROM injuries WHERE injury_id=?",
            (injury_id,),
        ).fetchone()
        if not row:
            return
        fighter_id, injury_type, severity, body_area, ret_date = row
    else:
        if fighter_id is None:
            return
        # No injury_id — try to look up by fight_id + fighter_id.
        row = conn.execute(
            "SELECT injury_type, severity, body_area, "
            "projected_return_date FROM injuries "
            "WHERE fighter_id=? AND (fight_id=? OR fight_id IS NULL) "
            "ORDER BY injury_id DESC LIMIT 1",
            (fighter_id, fight_id if fight_id is not None else -1),
        ).fetchone()
        if not row:
            return
        injury_type, severity, body_area, ret_date = row
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng, current_date=event_date,
    )
    attr_summary = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
    # v2.10.0 (FIX-VoiceRep): voice.describe_career_health descriptor
    # for the {health_state} body template slot (same fix as
    # generate_injury_news above).
    health_state = _fighter_career_health(conn, fighter_id, rng=rng)
    sev_phrase = _severity_phrase(severity)
    ret_phrase = _return_phrase(ret_date, event_date)
    injury_phrase = f"a {sev_phrase} {injury_type or 'injury'}"
    headline = rng.choice(_INJURY_HEADLINES).format(
        fighter=fighter_last, injury=injury_phrase,
    )
    body = rng.choice(_INJURY_BODY_TEMPLATES).format(
        fighter_full=fighter_full, fighter_last=fighter_last,
        career_stage=career_stage, art=_article_for(career_stage),
        attr_summary=attr_summary, health_state=health_state,
        injury=injury_phrase, return_phrase=ret_phrase,
    )
    _write_news_item(
        conn, headline, body, sentiment="negative",
        event_id=event_id, fight_id=fight_id, fighter_id=fighter_id,
        promotion_id=promo_id, published_at=event_date, rng=rng,
    )


def generate_injury_recovered_news(conn, event):
    """A5 — subscriber for INJURY_RECOVERED."""
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng,
        current_date=event.get("current_date") or event.get("event_date"),
    )
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    headline = rng.choice(_INJURY_RECOVERED_HEADLINES).format(
        fighter=fighter_last,
    )
    body = (
        f"{fighter_full}, {_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}, has been cleared to return to competition. "
        f"The medical team has signed off — the comeback trail begins."
    )
    _write_news_item(
        conn, headline, body, sentiment="positive",
        fighter_id=fighter_id, rng=rng,
        published_at=event.get("current_date") or event.get("event_date"),
    )


def generate_fighter_retired_news(conn, event):
    """A5 — subscriber for FIGHTER_RETIRED.

    Writes a career-retrospective news item using the same template
    pool as generate_retirement_news (the polling-based TICK_ADVANCED
    subscriber). The new event-driven subscriber fires immediately
    on retirement (no polling delay) and writes a single item; the
    polling subscriber still runs as a backstop for any retirement
    that somehow didn't publish the event (defensive).
    """
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    current_date = event.get("current_date") or event.get("event_date")
    rng = random.Random()
    # Reuse the rich retirement body builder by calling the existing
    # generate_retirement_news logic — but only for this one fighter.
    # Build the news item inline (avoid the polling dance).
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng, current_date=current_date,
    )
    attr_summary = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
    # v2.10.0 (FIX-VoiceRep): voice.describe_career_health descriptor
    # for the {health_state} body template slot (same fix as
    # generate_retirement_news above).
    health_state = _fighter_career_health(conn, fighter_id, rng=rng)
    career_row = conn.execute(
        "SELECT record_wins, record_losses, record_draws, "
        "title_reigns, career_health "
        "FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if career_row:
        wins, losses, draws, reigns, health = career_row
        wins_word = _num_word(wins or 0)
        losses_word = _num_word(losses or 0)
        reigns = reigns or 0
    else:
        wins_word = "several"
        losses_word = "several"
        reigns = 0
    if reigns > 0:
        reigns_word = _num_word(reigns)
        reign_phrase = f"A {reigns_word}-time champion,"
    else:
        reign_phrase = "A respected competitor,"
    legacy_phrase = rng.choice(_LEGACY_PHRASES).format(
        wins=wins_word, losses=losses_word,
    )
    promo_row = conn.execute(
        "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    promo_id = promo_row[0] if promo_row else None
    promotion_name = _promotion_name(conn, promo_id)
    headline = rng.choice(_RETIREMENT_HEADLINES).format(
        fighter=fighter_last,
    )
    body = rng.choice(_RETIREMENT_BODY_TEMPLATES).format(
        fighter_full=fighter_full, fighter_last=fighter_last,
        career_stage=career_stage,
        art=_article_for(career_stage),
        attr_summary=attr_summary, reign_phrase=reign_phrase,
        legacy_phrase=legacy_phrase, health_state=health_state,
        promotion_name=promotion_name,
    )
    _write_news_item(
        conn, headline, body, sentiment="neutral",
        fighter_id=fighter_id, promotion_id=promo_id,
        published_at=current_date, rng=rng,
    )


def generate_fighter_signed_news(conn, event):
    """A5 — subscriber for FIGHTER_SIGNED."""
    fighter_id = event.get("fighter_id")
    promotion_id = event.get("promotion_id")
    if fighter_id is None or promotion_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng,
        current_date=event.get("current_date") or event.get("event_date"),
    )
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    promotion_name = _promotion_name(conn, promotion_id)
    headline = rng.choice(_FIGHTER_SIGNED_HEADLINES).format(
        fighter=fighter_last, promotion=promotion_name,
    )
    body = (
        f"{fighter_full}, {_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}, has signed with {promotion_name}. The "
        f"promotion bolsters its roster — the fighter gets a fresh "
        f"start. Both sides will be hoping this is the beginning of "
        f"a long and profitable relationship."
    )
    _write_news_item(
        conn, headline, body, sentiment="positive",
        fighter_id=fighter_id, promotion_id=promotion_id, rng=rng,
        published_at=event.get("current_date") or event.get("event_date"),
    )


def generate_fighter_generated_news(conn, event):
    """A5 — subscriber for FIGHTER_GENERATED.

    Fires when the regen engine (tick_processor._check_retirements)
    creates a replacement fighter. The event payload includes the new
    fighter_id. Writes a "new prospect emerges" news item.
    """
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng,
        current_date=event.get("current_date") or event.get("event_date"),
    )
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    headline = rng.choice(_FIGHTER_GENERATED_HEADLINES).format(
        fighter=fighter_last,
    )
    body = (
        f"A new face has emerged on the scene: {fighter_full}, "
        f"{_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}. Whether they prove to be the next big thing "
        f"or just another name on the regional circuit remains to be "
        f"seen — but the scouts are paying attention."
    )
    _write_news_item(
        conn, headline, body, sentiment="neutral",
        fighter_id=fighter_id, rng=rng,
        published_at=event.get("current_date") or event.get("event_date"),
    )


def generate_contract_expired_news(conn, event):
    """A5 — subscriber for CONTRACT_EXPIRED."""
    fighter_id = event.get("fighter_id")
    promotion_id = event.get("promotion_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng,
        current_date=event.get("current_date") or event.get("event_date"),
    )
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    promotion_name = _promotion_name(conn, promotion_id)
    headline = rng.choice(_CONTRACT_EXPIRED_HEADLINES).format(
        fighter=fighter_last,
    )
    body = (
        f"{fighter_full}, {_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}, is now a free agent after their contract "
        f"with {promotion_name} expired. The open market awaits — "
        f"promotions will be weighing whether the fighter is worth "
        f"the investment, and the fighter will be weighing where "
        f"their next chapter should unfold."
    )
    _write_news_item(
        conn, headline, body, sentiment="neutral",
        fighter_id=fighter_id, promotion_id=promotion_id, rng=rng,
        published_at=event.get("current_date") or event.get("event_date"),
    )


def generate_scout_report_news(conn, event):
    """A5 — subscriber for SCOUT_REPORT_GENERATED."""
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng,
        current_date=event.get("current_date") or event.get("event_date"),
    )
    attr_summary = _short_descriptor_summary(conn, fighter_id, rng=rng)
    headline = rng.choice(_SCOUT_REPORT_HEADLINES).format(
        fighter=fighter_last,
    )
    body = (
        f"A new scout report has been filed on {fighter_full}, "
        f"{_article_for(career_stage)} {career_stage}, "
        f"{attr_summary}. The evaluation is in — the question now is "
        f"whether the fighter lives up to the billing or outperforms "
        f"the scouting department's projections."
    )
    _write_news_item(
        conn, headline, body, sentiment="neutral",
        fighter_id=fighter_id, rng=rng,
        published_at=event.get("current_date") or event.get("event_date"),
    )


def generate_weight_cut_news(conn, event):
    """A5 — subscriber for WEIGHT_CUT_COMPLETED.

    Fires after the weigh-in completes for both fighters on a fight.
    The event payload includes fighter_id, fight_id, event_id,
    weight_class_id, cut_outcome, weight_missed_kg. Writes a
    weigh-in results news item — no raw numbers per §14 (uses
    word-form phrases for the miss margin).
    """
    fighter_id = event.get("fighter_id")
    if fighter_id is None:
        return
    rng = random.Random()
    fighter_full = _fighter_full_name(conn, fighter_id)
    fighter_last = _fighter_last_name(conn, fighter_id)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng,
        current_date=event.get("current_date") or event.get("event_date"),
    )
    cut_outcome = event.get("cut_outcome", "made_weight") or "made_weight"
    headline = rng.choice(_WEIGHT_CUT_HEADLINES).format(
        fighter=fighter_last,
    )
    if cut_outcome == "made_weight":
        outcome_phrase = "made weight without issue"
    elif cut_outcome == "missed_small":
        outcome_phrase = "missed weight by a slim margin"
    elif cut_outcome == "missed_medium":
        outcome_phrase = "missed weight by a noticeable margin"
    elif cut_outcome == "missed_large":
        outcome_phrase = "missed weight badly — the fight is in jeopardy"
    elif cut_outcome == "cancelled":
        outcome_phrase = "missed weight by a wide margin; the fight was cancelled"
    else:
        outcome_phrase = "completed the cut"
    body = (
        f"{fighter_full}, {_article_for(career_stage)} {career_stage}, "
        f"{outcome_phrase} at the official weigh-in. The scale never "
        f"lies — and on fight week, it can be as much of an opponent "
        f"as the fighter across the cage."
    )
    _write_news_item(
        conn, headline, body, sentiment="neutral"
        if cut_outcome == "made_weight" else "negative",
        fight_id=event.get("fight_id"),
        event_id=event.get("event_id"),
        fighter_id=fighter_id,
        promotion_id=event.get("promotion_id"), rng=rng,
        published_at=event.get("current_date") or event.get("event_date"),
    )


def generate_event_recap_news(conn, event):
    """A5 — subscriber for EVENT_COMPLETED.

    Fires when an event transitions to 'completed' (all fights
    resolved). Writes a short recap news item naming the promotion
    and (if available) the headline result of the main event.
    Includes a career-stage descriptor for the winner so the recap
    has a voice-layer presence (CONVENTIONS §14 — no raw numbers).
    """
    event_id = event.get("event_id")
    promotion_id = event.get("promotion_id")
    event_date = event.get("event_date") or event.get("current_date")
    if event_id is None:
        return
    rng = random.Random()
    promotion_name = _promotion_name(conn, promotion_id)
    headline = rng.choice(_EVENT_RECAP_HEADLINES).format(
        promotion=promotion_name,
    )
    # Find the main event result for the body (highest card_slot
    # fight with a winner). Word-form result_label — no raw numbers.
    main_row = conn.execute(
        "SELECT f.winner_fighter_id, f.loser_fighter_id, f.result_type "
        "FROM fights f WHERE f.event_id=? "
        "AND f.winner_fighter_id IS NOT NULL "
        "ORDER BY f.card_slot DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    if main_row:
        winner_id, loser_id, result_type = main_row
        winner_full = _fighter_full_name(conn, winner_id) if winner_id else "the winner"
        loser_full = _fighter_full_name(conn, loser_id) if loser_id else "the loser"
        result_label = _result_label(result_type)
        # Voice-layer career stage for the winner — gives the recap
        # a voice presence (§14 — no raw numbers; "reigning champion"
        # / "top prospect" etc.).
        winner_stage = _fighter_career_stage(
            conn, winner_id, rng=rng, current_date=event_date,
        ) if winner_id else "competitor"
        body = (
            f"The {promotion_name} card is in the books. In the main "
            f"event, {winner_full} — {_article_for(winner_stage)} "
            f"{winner_stage} — earned {result_label} over "
            f"{loser_full}. The rest of the card delivered its share "
            f"of storylines; the division reshuffles as the dust "
            f"settles and the fighters turn an eye toward what "
            f"comes next."
        )
    else:
        body = (
            f"The {promotion_name} card has wrapped. The full results "
            f"are filtering through the wire — the division reshuffles "
            f"as the dust settles and the fighters turn an eye toward "
            f"what comes next."
        )
    _write_news_item(
        conn, headline, body, sentiment="neutral",
        event_id=event_id, promotion_id=promotion_id, rng=rng,
        published_at=event_date,
    )


# ----------------------------------------------------------------
# SUSPENSION NEWS — Phase B polling subscriber for TICK_ADVANCED.
#
# Per the Phase B brief: the suspensions module (src/suspensions.py)
# writes suspension ROWS directly (no event bus publish for the
# creation — only FIGHT_RESOLVED triggers the roll, and TICK_ADVANCED
# triggers the recovery). The news engine picks up new + cleared
# suspensions via this TICK_ADVANCED polling subscriber (same pattern
# as generate_retirement_news — polls for state changes, writes
# voice-layer-driven news items).
#
# Two flavors of news:
#   1. CREATION — active suspension (is_active=1) with no creation
#      news item yet. Writes a scandal-style headline + body. The
#      career-stage descriptor (voice.describe_career_stage) gives
#      narrative weight: "the reigning champion fails a drug test"
#      is a generational scandal; "an unproven prospect fails a drug
#      test" is a cautionary tale. Tabloid sources (The Cage Wire)
#      get "BREAKING:" / "SHOCK:" prefixes; broadsheet sources
#      (MMA Analytica) get "Analysis:" prefixes (handled by
#      _apply_source_tone in _write_news_item).
#   2. CLEARANCE — cleared suspension (is_active=0) with no clearance
#      news item yet. Writes a "cleared to return" / "suspension
#      lifted" headline. The fighter's career-stage descriptor
#      frames the comeback: "the former champion returns from the
#      wilderness" vs "the prospect puts a mistake behind them".
#
# Dedup: each suspension_id gets at most ONE creation news item and
# at most ONE clearance news item. The dedup checks for a body
# containing the literal suspension_id marker (e.g.
# "[suspension_id=42]") so we never write a duplicate. The marker
# is appended to the body (not displayed in the UI — it's a hidden
# audit trail for the dedup query).
# ----------------------------------------------------------------

SUSPENSION_TOPIC = "suspension"

# Creation news headlines. The {fighter} slot is the fighter's last
# name (short for headline impact). The {type_phrase} slot is one of
# the _SUSPENSION_TYPE_PHRASES entries (e.g. "fails drug test",
# "hit with behavior ban"). NO digit characters (CONVENTIONS §14).
_SUSPENSION_CREATE_HEADLINES = [
    "BREAKING: {fighter} {type_phrase}",
    "{fighter} {type_phrase} — sidelined indefinitely",
    "Scandal rocks the division — {fighter} {type_phrase}",
    "{fighter} handed a suspension after latest incident",
    "Commission comes down hard on {fighter}",
    "{fighter} {type_phrase} in stunning development",
]

# Maps suspension_type → verb phrase for the headline {type_phrase}
# slot. Each phrase has multiple variants; the rng picks one. Word-
# form only — NO digit characters (CONVENTIONS §14).
_SUSPENSION_TYPE_PHRASES = {
    "drug_test_failure": [
        "fails drug test", "flagged for a banned substance",
        "caught by commission testing",
    ],
    "behavior": [
        "hit with behavior ban", "suspended for conduct",
        "draws a behavioral suspension",
    ],
    "missed_weight_repeat": [
        "suspended for repeat weight misses",
        "hit with a weight-cut ban",
    ],
    "post_fight_brawl": [
        "suspended for post-fight brawl",
        "banned for the post-fight melee",
    ],
    "social_media_violation": [
        "suspended over a social media post",
        "hit with a social media violation ban",
    ],
}

# Duration phrases — word-form only (CONVENTIONS §14). Maps the
# suspension_type to a list of phrases describing the typical
# duration. The actual duration_days is INTERNAL — the player sees
# "an extended ban" or "the rest of the year", never "180 days".
_SUSPENSION_DURATION_PHRASES = {
    "drug_test_failure": [
        "an extended ban", "a lengthy suspension",
        "a ban that will keep them out for some time",
        "a suspension spanning the better part of a year",
    ],
    "behavior": [
        "a multi-month suspension", "a several-month ban",
        "a suspension measured in months rather than weeks",
    ],
    "missed_weight_repeat": [
        "a short-term suspension", "a brief commission ban",
    ],
    "post_fight_brawl": [
        "a stiff suspension", "a ban meant to send a message",
    ],
    "social_media_violation": [
        "a short suspension", "a cooling-off period ban",
    ],
}

_SUSPENSION_CREATE_BODY_TEMPLATES = [
    "{fighter_full}, {art} {career_stage}, {attr_summary}, has been "
    "suspended by the commission. The {type_phrase_noun} means "
    "{fighter_last} sits on the shelf for {duration_phrase}. The "
    "{promotion_name} roster reshuffles without them — the division "
    "moves on, and the fighter is left to wait.",

    "The commission has handed down {duration_phrase} to {fighter_full} "
    "({art} {career_stage}) {attr_summary}. {fighter_last} will be "
    "unavailable for booking until the suspension lifts — a serious "
    "blow for a fighter who was building momentum. The {promotion_name} "
    "brass now has to plan around the absence.",

    "In a story that will define {fighter_last}'s career arc, "
    "{fighter_full} ({art} {career_stage}) {attr_summary} faces "
    "{duration_phrase}. The suspension is the kind of off-cage "
    "headline no fighter wants — the {promotion_name} fighter now "
    "faces a long road back to relevance.",
]

# Clearance news headlines + bodies. The "return from the wilderness"
# narrative — the suspension lifts, the fighter comes back.
_SUSPENSION_CLEAR_HEADLINES = [
    "{fighter} cleared to return from suspension",
    "Suspension lifted — {fighter} eligible to compete again",
    "{fighter} back in the mix after serving ban",
    "The wait is over — {fighter} returns from suspension",
    "{fighter} reinstated by the commission",
]

_SUSPENSION_CLEAR_BODY_TEMPLATES = [
    "{fighter_full}, {art} {career_stage}, has been cleared to return "
    "after serving {duration_phrase}. {fighter_last} is eligible to "
    "compete once more — the {promotion_name} roster adds a familiar "
    "name back to the mix. The comeback starts now.",

    "After {duration_phrase} on the shelf, {fighter_full} ({art} "
    "{career_stage}) is back. {fighter_last} served the suspension "
    "and is once again available for booking — the {promotion_name} "
    "brass can finally write the next chapter.",

    "The suspension is behind them. {fighter_full} ({art} "
    "{career_stage}) {attr_summary} returns to action after "
    "{duration_phrase}. {fighter_last} steps back into the "
    "{promotion_name} picture — older, wiser, and eager to rewrite "
    "the story.",
]


def _suspension_id_marker(suspension_id, flavor):
    """Build the hidden dedup marker for a suspension news item body.

    The marker is appended to the body text (not displayed in the
    UI — it's a hidden audit trail for the dedup query). Format:
    "[suspension_id=42:create]" or "[suspension_id=42:clear]".

    The flavor suffix distinguishes creation news from clearance
    news so each suspension_id can have at most ONE of each flavor
    (the dedup query checks for the exact marker substring,
    including the flavor suffix).
    """
    if flavor not in ("create", "clear"):
        raise ValueError(f"unknown suspension news flavor {flavor!r}")
    return f"[suspension_id={suspension_id}:{flavor}]"


def _has_suspension_news(conn, suspension_id, flavor):
    """Return True if a suspension news item already exists for this
    suspension_id + flavor ('create' or 'clear').

    Dedup is based on the hidden _suspension_id_marker (with flavor
    suffix) in the body. Each suspension_id gets at most ONE creation
    news item and at most ONE clearance news item.
    """
    marker = _suspension_id_marker(suspension_id, flavor)
    row = conn.execute(
        "SELECT 1 FROM news_items WHERE topic=? AND body LIKE ?",
        (SUSPENSION_TOPIC, f"%{marker}%"),
    ).fetchone()
    return row is not None


def generate_suspension_news(conn, event):
    """Phase B — TICK_ADVANCED polling subscriber for suspension news.

    Scans the `suspensions` table for:
      1. Active suspensions (is_active=1) with no creation news item
         yet → writes a scandal-style creation news item.
      2. Cleared suspensions (is_active=0) with no clearance news
         item yet → writes a clearance / "return" news item.

    Uses voice-layer descriptors (career_stage + attr_summary) per
    CONVENTIONS §14. Duration is described via word-form phrases
    ("an extended ban", "a multi-month suspension") — never the
    raw duration_days integer.

    Dedup: each suspension_id gets at most one creation news item
    and at most one clearance news item. The dedup uses a hidden
    [suspension_id=N] marker appended to the body (queried via
    LIKE — see _has_suspension_news).

    This polling pattern mirrors generate_retirement_news (which
    polls for 'retirement' topic news items written by the inline
    tick_processor._check_retirements). The suspension creation
    happens in the FIGHT_RESOLVED subscriber (suspensions.
    _maybe_random_suspension); the clearance happens in the
    TICK_ADVANCED subscriber (suspensions.check_suspension_recovery).
    Both write only the suspensions row — this news subscriber
    writes the narrative, picked up via the polling scan.
    """
    current_date = event.get("current_date")
    if not current_date:
        return

    rng = random.Random()

    # ----- 1. Creation news for active suspensions ----------------
    active = conn.execute(
        "SELECT suspension_id, fighter_id, suspension_type, "
        "start_date, end_date, duration_days "
        "FROM suspensions WHERE is_active=1"
    ).fetchall()
    for (susp_id, fighter_id, susp_type, start_date,
         end_date, duration_days) in active:
        if _has_suspension_news(conn, susp_id, "create"):
            continue  # already wrote the creation news

        fighter_full = _fighter_full_name(conn, fighter_id)
        fighter_last = _fighter_last_name(conn, fighter_id)
        career_stage = _fighter_career_stage(
            conn, fighter_id, rng=rng, current_date=current_date,
        )
        attr_summary = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
        type_phrase = rng.choice(
            _SUSPENSION_TYPE_PHRASES.get(susp_type, ["suspended"])
        )
        duration_phrase = rng.choice(
            _SUSPENSION_DURATION_PHRASES.get(susp_type, ["a suspension"])
        )
        # Type noun for the body template (e.g. "drug test failure"
        # → "the failed drug test"). Uses the same phrases — the
        # context makes the noun form natural.
        type_phrase_noun = rng.choice(
            _SUSPENSION_TYPE_PHRASES.get(susp_type, ["the suspension"])
        )
        # Look up the fighter's promotion for the body context.
        promo_row = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        promo_id = promo_row[0] if promo_row else None
        promotion_name = _promotion_name(conn, promo_id)

        headline = rng.choice(_SUSPENSION_CREATE_HEADLINES).format(
            fighter=fighter_last, type_phrase=type_phrase,
        )
        body_template = rng.choice(_SUSPENSION_CREATE_BODY_TEMPLATES)
        body = body_template.format(
            fighter_full=fighter_full, fighter_last=fighter_last,
            career_stage=career_stage, art=_article_for(career_stage),
            attr_summary=attr_summary, type_phrase_noun=type_phrase_noun,
            duration_phrase=duration_phrase,
            promotion_name=promotion_name,
        )
        # Append the hidden dedup marker (not displayed — used by
        # _has_suspension_news to prevent duplicate news items).
        body = body + " " + _suspension_id_marker(susp_id, "create")
        _write_news_item(
            conn, headline, body, sentiment="negative",
            fighter_id=fighter_id, promotion_id=promo_id, rng=rng,
            published_at=current_date, topic=SUSPENSION_TOPIC,
        )

    # ----- 2. Clearance news for cleared suspensions --------------
    cleared = conn.execute(
        "SELECT suspension_id, fighter_id, suspension_type, "
        "start_date, end_date, duration_days "
        "FROM suspensions WHERE is_active=0"
    ).fetchall()
    for (susp_id, fighter_id, susp_type, start_date,
         end_date, duration_days) in cleared:
        if _has_suspension_news(conn, susp_id, "clear"):
            continue  # already wrote the clearance news
        # Only write clearance news if the creation news has been
        # written (defensive — a suspension that was seeded directly
        # into is_active=0 state shouldn't generate a clearance
        # story with no preceding suspension story).
        if not _has_suspension_news(conn, susp_id, "create"):
            continue

        fighter_full = _fighter_full_name(conn, fighter_id)
        fighter_last = _fighter_last_name(conn, fighter_id)
        career_stage = _fighter_career_stage(
            conn, fighter_id, rng=rng, current_date=current_date,
        )
        attr_summary = _fighter_descriptor_summary(conn, fighter_id, rng=rng)
        duration_phrase = rng.choice(
            _SUSPENSION_DURATION_PHRASES.get(susp_type, ["a suspension"])
        )
        promo_row = conn.execute(
            "SELECT current_promotion_id FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        promo_id = promo_row[0] if promo_row else None
        promotion_name = _promotion_name(conn, promo_id)

        headline = rng.choice(_SUSPENSION_CLEAR_HEADLINES).format(
            fighter=fighter_last,
        )
        body_template = rng.choice(_SUSPENSION_CLEAR_BODY_TEMPLATES)
        body = body_template.format(
            fighter_full=fighter_full, fighter_last=fighter_last,
            career_stage=career_stage, art=_article_for(career_stage),
            attr_summary=attr_summary,
            duration_phrase=duration_phrase,
            promotion_name=promotion_name,
        )
        body = body + " " + _suspension_id_marker(susp_id, "clear")
        _write_news_item(
            conn, headline, body, sentiment="positive",
            fighter_id=fighter_id, promotion_id=promo_id, rng=rng,
            published_at=current_date, topic=SUSPENSION_TOPIC,
        )


# ----------------------------------------------------------------
# A6 — news pruning. Weekly TICK_ADVANCED subscriber that deletes
# news_items older than 365 days EXCEPT for items with topic IN
# ('title', 'retirement', 'hall_of_fame') which are kept forever
# (title change news, retirements, and HoF inductions are legacy
# artifacts the player wants to browse years later).
# ----------------------------------------------------------------

# Topics that are exempt from pruning (kept forever).
# 'suspension' (Phase B) is kept — a drug-test scandal or behavioral
# suspension is a legacy story the player wants to browse years later
# (the "whatever happened to that guy?" thread). Same rationale as
# 'title' / 'retirement' / 'hall_of_fame' / 'memory_resurfacing'.
_NEWS_PRUNE_KEEP_TOPICS = frozenset({
    "title", "retirement", "hall_of_fame", "memory_resurfacing",
    "suspension",
})

# Pruning threshold — news older than this many days is pruned.
_NEWS_PRUNE_AGE_DAYS = 365


def _is_weekly_tick(conn):
    """Return True if the current sim day is a multiple of 7 (weekly tick)."""
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not row or row[0] is None:
        return False
    return (row[0] % 7) == 0


def prune_old_news(conn, event):
    """A6 — weekly TICK_ADVANCED subscriber that prunes old news items.

    Deletes news_items older than _NEWS_PRUNE_AGE_DAYS (365) EXCEPT
    for items with topic IN ('title', 'retirement', 'hall_of_fame')
    which are kept forever (title change news, retirements, and HoF
    inductions are legacy artifacts).

    Pruning is a hard DELETE (no archive table — the brief explicitly
    says "keep it simple"). Runs only on weekly ticks (current_day %
    7 == 0) to avoid deleting on every daily tick (which would be
    wasteful and could surprise a player mid-week).

    The prune uses published_at < date(current_date, '-365 days') to
    compute the cutoff. If published_at is NULL (shouldn't happen —
    the column has a DEFAULT), the row is kept (defensive — we don't
    want to delete news with unknown publish dates).
    """
    if not _is_weekly_tick(conn):
        return
    current_date = event.get("current_date")
    if not current_date:
        return
    # Build the keep-topic IN (...) clause. The topics are hardcoded
    # constants so SQL injection isn't a concern, but use a parameter
    # list for clarity.
    placeholders = ",".join("?" for _ in _NEWS_PRUNE_KEEP_TOPICS)
    conn.execute(
        f"DELETE FROM news_items "
        f"WHERE published_at IS NOT NULL "
        f"AND published_at < date(?, '-{365} days') "
        f"AND topic NOT IN ({placeholders})",
        [current_date] + list(_NEWS_PRUNE_KEEP_TOPICS),
    )


# ----------------------------------------------------------------
# Phase C — Upcoming Event Hype news.
#
# Per docs/FULL_BUILD_AUDIT.md §9d: no pre-event hype generation.
# This subscriber fires on weekly TICK_ADVANCED and writes hype news
# for any scheduled event in the next 7 days. Each event gets at
# most 2 hype news items (dedup via hidden [event_hype:event_id:N]
# marker in the body). 3-4 template variants per hype type for
# variety. Voice-layer-driven per §14 — uses career-stage
# descriptors + voice attribute descriptors, no raw numbers.
#
# 3 hype types per event:
#   1. CARD_ANNOUNCE — "{promotion} announces {date} card — {a} vs {b}"
#   2. WEIGH_IN_APPROACHES — "Weigh-in day approaches for {promotion}'s event"
#   3. TRAINING_FOCUS — "{fighter} trains hard for upcoming {opponent} clash"
#
# The subscriber writes at most 2 hype items per event (the brief
# says "max 2 hype news items per event (don't spam)"). The 2 are
# picked from the 3 hype types — the RNG picks 2 of the 3 (without
# replacement) so each event gets a different mix of hype items.
# ----------------------------------------------------------------

# Topics for the hype subscribers. Each is kept by the A6 pruner
# (legacy: hype news is short-lived — actually we WANT hype news
# pruned normally, so we do NOT add these to _NEWS_PRUNE_KEEP_TOPICS).
EVENT_HYPE_TOPIC = "event_hype"
CROSS_PROMO_TOPIC = "cross_promo"

# Hype headline templates per hype type (3-4 variants each).
_HYPE_HEADLINES_CARD_ANNOUNCE = [
    "{promotion} announces upcoming card — {a} vs {b} in the main event",
    "{promotion} sets {a} vs {b} as the headline of the next card",
    "Next {promotion} card locked in — {a} meets {b} in the main event",
    "{a} vs {b} headlines {promotion}'s upcoming event",
]

_HYPE_HEADLINES_WEIGH_IN = [
    "Weigh-in day approaches for {promotion}'s upcoming event",
    "{promotion} fighters cut down to weight ahead of fight week",
    "The scale looms — {promotion} weigh-ins on the horizon",
    "Fight week begins — {promotion} athletes face the cut",
]

_HYPE_HEADLINES_TRAINING = [
    "{fighter} trains hard for upcoming {opponent} clash",
    "{fighter} puts in the rounds ahead of {opponent} showdown",
    "Camp grinds on — {fighter} preps for {opponent}",
    "{fighter} sharpens the tools for the {opponent} fight",
]

_HYPE_BODY_CARD_ANNOUNCE = [
    "{promotion_name} has locked in its next card. The main event "
    "pits {a_full} — {a_art} {a_stage} {a_attr} — against {b_full}, "
    "{b_art} {b_stage} {b_attr}. The date is set; the buildup begins.",

    "The next {promotion_name} card has its headline bout. {a_full} "
    "({a_art} {a_stage} {a_attr}) answers the call against {b_full} "
    "({b_art} {b_stage} {b_attr}). Two fighters, one date, one "
    "question — who takes the next step?",

    "{promotion_name} matchmakers have done their work. {a_full} — "
    "{a_art} {a_stage} {a_attr} — headlines the upcoming card "
    "opposite {b_full}, {b_art} {b_stage} {b_attr}. The matchup "
    "writes itself; now the fighters have to write the ending.",

    "Mark the date — {promotion_name} returns with a main event "
    "worth circling. {a_full} ({a_art} {a_stage} {a_attr}) takes on "
    "{b_full} ({b_art} {b_stage} {b_attr}) in a fight that could "
    "reshape the division.",
]

_HYPE_BODY_WEIGH_IN = [
    "Fight week has arrived for {promotion_name}. The athletes face "
    "the scale before they face each other — and the cut is its own "
    "kind of war. {a_full} and {b_full} both have to make weight "
    "before the main event can happen.",

    "The {promotion_name} card is days away, which means the weight "
    "cut begins in earnest. {a_full} ({a_art} {a_stage}) and "
    "{b_full} ({b_art} {b_stage}) both have to step on the scale — "
    "and a bad cut can derail a fight as fast as a bad opponent.",

    "Weigh-in day looms for the {promotion_name} card. {a_full} and "
    "{b_full} both have to hit the mark — and the scale has ended "
    "more fights than the cage ever did. The cut is part of the "
    "sport; sometimes it's the hardest part.",

    "{promotion_name} fight week is here. The main event between "
    "{a_full} and {b_full} can't happen until both make weight. "
    "The cut is a chess match of its own — rehydrate, refuel, "
    "and try to walk into the cage as close to full strength as "
    "the scale allows.",
]

_HYPE_BODY_TRAINING = [
    "{a_full}, {a_art} {a_stage} {a_attr}, is deep in camp ahead of "
    "the {b_last} fight. The work is unglamorous — rounds on rounds, "
    "film study, weight management, recovery. But the work is what "
    "shows up on fight night, and {a_last} knows it.",

    "Camp for {a_full} ({a_art} {a_stage} {a_attr}) is grinding "
    "toward the {b_last} showdown. The {promotion_name} {a_stage} "
    "is putting in the rounds — sparring partners, drilling, "
    "conditioning — building the form that will travel into the "
    "cage on fight night.",

    "{a_full} ({a_art} {a_stage}) {a_attr} is sharpening every tool "
    "ahead of the {b_last} clash. The {promotion_name} card is "
    "approaching and {a_last} knows the work put in now is the work "
    "that shows up under the lights.",

    "The buildup for {a_full} vs {b_full} is well underway. {a_full} "
    "— {a_art} {a_stage} {a_attr} — is in the gym, in the film "
    "room, in the weight cut. The {promotion_name} main event is "
    "weeks away; the work is now.",
]


def _event_hype_dedup_marker(event_id, hype_type, n=1):
    """Build the hidden dedup marker for an event hype news item body.

    The marker is appended to the body text (not displayed in the
    UI — it's a hidden audit trail for the dedup query). Format:
    "[event_hype:event_id=42:type=card_announce:n=1]".

    The `n` suffix distinguishes the 1st hype item from the 2nd so
    each (event_id, hype_type, n) triple gets at most one news item.
    """
    return f"[event_hype:event_id={event_id}:type={hype_type}:n={n}]"


def _has_event_hype_news(conn, event_id, hype_type, n=1):
    """Return True if an event hype news item already exists for this
    (event_id, hype_type, n) triple.
    """
    marker = _event_hype_dedup_marker(event_id, hype_type, n)
    row = conn.execute(
        "SELECT 1 FROM news_items WHERE topic=? AND body LIKE ?",
        (EVENT_HYPE_TOPIC, f"%{marker}%"),
    ).fetchone()
    return row is not None


def _get_main_event_for_event(conn, event_id):
    """Return (fighter_a_id, fighter_b_id) for the main event of an
    event, or (None, None) if no main event exists.

    The main event is the fight with the highest card_slot ('main_
    event' tier) — picked via ORDER BY card_slot DESC LIMIT 1 to
    handle legacy rows that may not have is_main_event=1 set.
    """
    row = conn.execute(
        "SELECT fp_a.fighter_id, fp_b.fighter_id "
        "FROM fights f "
        "JOIN event_cards ec ON ec.fight_id = f.fight_id "
        "JOIN fight_participants fp_a ON fp_a.fight_id = f.fight_id "
        "  AND fp_a.corner = 'red' "
        "JOIN fight_participants fp_b ON fp_b.fight_id = f.fight_id "
        "  AND fp_b.corner = 'blue' "
        "WHERE f.event_id = ? "
        "ORDER BY ec.card_position ASC, f.card_slot DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    if not row:
        # Fallback — pick any fight on the event with 2 participants.
        row = conn.execute(
            "SELECT fp_a.fighter_id, fp_b.fighter_id "
            "FROM fights f "
            "JOIN fight_participants fp_a ON fp_a.fight_id = f.fight_id "
            "  AND fp_a.corner = 'red' "
            "JOIN fight_participants fp_b ON fp_b.fight_id = f.fight_id "
            "  AND fp_b.corner = 'blue' "
            "WHERE f.event_id = ? "
            "ORDER BY f.card_slot DESC LIMIT 1",
            (event_id,),
        ).fetchone()
    if not row:
        return (None, None)
    return (row[0], row[1])


def generate_event_hype_news(conn, event):
    """Phase C — TICK_ADVANCED subscriber for upcoming event hype news.

    Fires on weekly ticks. For each scheduled event in the next 7
    days (event_date BETWEEN current_date AND current_date + 7 days,
    status='scheduled'), generates up to 2 hype news items. Each
    event gets at most 2 hype items (dedup via hidden marker).

    Hype types (3 — RNG picks 2 of 3 per event):
      1. card_announce — "{promotion} announces {date} card — {a} vs {b}"
      2. weigh_in — "Weigh-in day approaches for {promotion}'s event"
      3. training — "{fighter} trains hard for upcoming {opponent} clash"

    Uses voice-layer descriptors (career_stage + top-2 attributes)
    per CONVENTIONS §14. NO raw numbers in any hype text.
    """
    if not _is_weekly_tick(conn):
        return
    current_date = event.get("current_date")
    if not current_date:
        return

    rng = random.Random()

    # Find scheduled events in the next 7 days.
    upcoming = conn.execute(
        "SELECT event_id, promotion_id, event_name, event_date "
        "FROM events "
        "WHERE status = 'scheduled' "
        "AND event_date >= ? AND event_date <= date(?, '+7 days') "
        "ORDER BY event_date ASC",
        (current_date, current_date),
    ).fetchall()

    for (event_id, promo_id, event_name, event_date) in upcoming:
        a_id, b_id = _get_main_event_for_event(conn, event_id)
        if a_id is None or b_id is None:
            continue  # no main event — skip

        # Pick 2 of the 3 hype types (without replacement).
        hype_types = ['card_announce', 'weigh_in', 'training']
        rng.shuffle(hype_types)
        chosen = hype_types[:2]

        for n, hype_type in enumerate(chosen, start=1):
            # Dedup — at most 1 news item per (event_id, hype_type, n).
            if _has_event_hype_news(conn, event_id, hype_type, n):
                continue

            a_full = _fighter_full_name(conn, a_id)
            b_full = _fighter_full_name(conn, b_id)
            a_last = _fighter_last_name(conn, a_id)
            b_last = _fighter_last_name(conn, b_id)
            a_stage = _fighter_career_stage(
                conn, a_id, rng=rng, current_date=current_date,
            )
            b_stage = _fighter_career_stage(
                conn, b_id, rng=rng, current_date=current_date,
            )
            a_attr = _fighter_descriptor_summary(conn, a_id, rng=rng)
            b_attr = _fighter_descriptor_summary(conn, b_id, rng=rng)
            promotion_name = _promotion_name(conn, promo_id)

            if hype_type == 'card_announce':
                headline = rng.choice(_HYPE_HEADLINES_CARD_ANNOUNCE).format(
                    promotion=promotion_name, a=a_last, b=b_last,
                )
                body = rng.choice(_HYPE_BODY_CARD_ANNOUNCE).format(
                    promotion_name=promotion_name,
                    a_full=a_full, b_full=b_full,
                    a_art=_article_for(a_stage), b_art=_article_for(b_stage),
                    a_stage=a_stage, b_stage=b_stage,
                    a_attr=a_attr, b_attr=b_attr,
                )
            elif hype_type == 'weigh_in':
                headline = rng.choice(_HYPE_HEADLINES_WEIGH_IN).format(
                    promotion=promotion_name,
                )
                body = rng.choice(_HYPE_BODY_WEIGH_IN).format(
                    promotion_name=promotion_name,
                    a_full=a_full, b_full=b_full,
                    a_art=_article_for(a_stage), b_art=_article_for(b_stage),
                    a_stage=a_stage, b_stage=b_stage,
                )
            else:  # training
                # Pick which fighter to spotlight (50/50).
                spot_id, opp_id, spot_full, opp_last, spot_stage, spot_attr, spot_art = (
                    rng.choice([
                        (a_id, b_id, a_full, b_last, a_stage, a_attr,
                         _article_for(a_stage)),
                        (b_id, a_id, b_full, a_last, b_stage, b_attr,
                         _article_for(b_stage)),
                    ])
                )
                opp_full = _fighter_full_name(conn, opp_id)
                headline = rng.choice(_HYPE_HEADLINES_TRAINING).format(
                    fighter=spot_full, opponent=opp_last,
                )
                body = rng.choice(_HYPE_BODY_TRAINING).format(
                    promotion_name=promotion_name,
                    a_full=spot_full, a_last=_fighter_last_name(conn, spot_id),
                    a_art=spot_art, a_stage=spot_stage, a_attr=spot_attr,
                    b_last=opp_last, b_full=opp_full,
                )

            # Append the hidden dedup marker.
            body = body + " " + _event_hype_dedup_marker(
                event_id, hype_type, n,
            )

            _write_news_item(
                conn, headline, body, sentiment="positive",
                event_id=event_id, promotion_id=promo_id,
                fighter_id=a_id, rng=rng, published_at=current_date,
                topic=EVENT_HYPE_TOPIC,
            )


# ----------------------------------------------------------------
# Phase C — Cross-Promotion News.
#
# Per docs/FULL_BUILD_AUDIT.md §9e: the player should hear about
# big events in rival promotions. Two subscribers:
#
# 1. generate_cross_promo_title_news — TITLE_CHANGED subscriber.
#    Fires when a title changes hands in a NON-player promotion
#    (promotion_id != 1). Always generates cross-promo news — a
#    title change in a rival promotion is notable by definition.
#
# 2. generate_cross_promo_fight_news — FIGHT_RESOLVED subscriber.
#    Fires for non-player promotion fights. Only generates cross-
#    promo news for BIG UPSETS — underdog with a significantly
#    worse record (or a 3+ losing streak) wins by KO/submission.
#    Title fights are EXCLUDED here (they're covered by the
#    TITLE_CHANGED subscriber above — avoid duplicate coverage).
#
# Cross-promo news is RARE and NOTABLE per the brief — most rival
# promotion fights generate no cross-promo news. The filtering is
# deliberate: only title changes + big upsets clear the bar.
# ----------------------------------------------------------------

# The player's promotion — cross-promo news is only generated for
# NON-player promotions (the player already sees their own promotion's
# news via the standard subscribers). The small seed assigns Alpha
# Combat promotion_id=1; the world seed's first promotion is also
# id=1 by AUTOINCREMENT.
_PLAYER_PROMOTION_ID = 1

# Big-upset thresholds (used by generate_cross_promo_fight_news to
# decide whether a non-player promotion fight is "notable" enough
# for cross-promo news).
_BIG_UPSET_LOSS_STREAK_MIN = 3     # winner was on a 3+ losing streak
_BIG_UPSET_RECORD_GAP_MIN = 5     # winner had 5+ fewer wins than loser
_BIG_UPSET_WIN_STREAK_LOSER_MIN = 4  # loser was on a 4+ win streak

_CROSS_PROMO_HEADLINES_TITLE_NEW_CHAMP = [
    "Across the pond: {rival} champion {winner} claims the throne",
    "Rival promotion {rival} crowns a new champion — {winner} takes gold",
    "{rival} title changes hands — {winner} is the new king of the division",
    "The {rival} belt finds a new home — {winner} ascends",
]

_CROSS_PROMO_HEADLINES_TITLE_DEFENSE = [
    "Across the pond: {rival} champion {winner} defends title",
    "{rival} champ {winner} turns back challenger — reign continues",
    "{rival} titleholder {winner} retains the crown",
    "{winner} defends {rival} gold — the reign rolls on",
]

_CROSS_PROMO_HEADLINES_UPSET = [
    "Across the pond: {rival} sees a big upset — {winner} stuns {loser}",
    "Rival promotion {rival} rocked — {winner} pulls off the upset over {loser}",
    "Shock result in {rival} — {winner} shocks {loser}",
    "{rival} upset alert — {winner} pulls off the unthinkable against {loser}",
]

_CROSS_PROMO_BODY_TITLE_NEW_CHAMP = [
    "{winner_full}, {winner_art} {winner_stage} {winner_attr}, has "
    "captured the {rival_promotion} title — dethroning the previous "
    "champion in the process. The {rival_promotion} division has a "
    "new face at the top, and the rest of the sport is paying "
    "attention. Cross-promotion storylines write themselves when a "
    "belt changes hands in a rival room.",

    "Gold changes hands in {rival_promotion}. {winner_full} "
    "({winner_art} {winner_stage}) {winner_attr} is the new champion, "
    "and the {rival_promotion} hierarchy has been reshuffled. Whether "
    "the new champ's reign sparks a cross-promotion superfight "
    "conversation remains to be seen — but the MMA world is "
    "watching.",

    "A new champion in {rival_promotion}: {winner_full} — {winner_art} "
    "{winner_stage} {winner_attr} — sits atop the division after "
    "dethroning the previous titleholder. The {rival_promotion} "
    "roster has a new face at the top, and the ripple effects will "
    "be felt across the sport's landscape.",
]

_CROSS_PROMO_BODY_TITLE_DEFENSE = [
    "{winner_full}, {winner_art} {winner_stage} {winner_attr}, "
    "defends the {rival_promotion} title — turning back the "
    "challenger and extending the reign. The {rival_promotion} "
    "champion is still the champion, and the rest of the division "
    "is still chasing.",

    "Title defense in the books for {winner_full} ({winner_art} "
    "{winner_stage}) {winner_attr} — the {rival_promotion} belt "
    "stays put. Another challenger handled, another night at the "
    "top. The {rival_promotion} champion is building a resume "
    "worth noticing.",

    "{winner_full} ({winner_art} {winner_stage}) {winner_attr} "
    "retains the {rival_promotion} title. The challenger came up "
    "short — the reign continues. The {rival_promotion} champion "
    "is still the one to beat, and the rest of the sport is "
    "taking notes.",
]

_CROSS_PROMO_BODY_UPSET = [
    "{winner_full}, {winner_art} {winner_stage} {winner_attr}, "
    "pulled off a stunning upset in {rival_promotion} — defeating "
    "{loser_full} ({loser_art} {loser_stage}) {loser_attr} in a "
    "result nobody saw coming. The {rival_promotion} division just "
    "got a shake-up, and the rest of the sport is taking note.",

    "Shock result in {rival_promotion}: {winner_full} "
    "({winner_art} {winner_stage}) {winner_attr} stunned "
    "{loser_full} ({loser_art} {loser_stage}) {loser_attr} in a "
    "fight that flips the {rival_promotion} hierarchy on its head. "
    "The upset will be talked about across the sport for weeks.",

    "Big upset in {rival_promotion} — {winner_full} "
    "({winner_art} {winner_stage}) {winner_attr} took out "
    "{loser_full} ({loser_art} {loser_stage}) {loser_attr} in a "
    "result that nobody — not the oddsmakers, not the pundits, "
    "not the {rival_promotion} brass — saw coming. The "
    "{rival_promotion} division has a new storyline.",
]


def generate_cross_promo_title_news(conn, event):
    """Phase C — TITLE_CHANGED subscriber for cross-promotion title news.

    Fires when a title changes hands in a NON-player promotion
    (promotion_id != PLAYER_PROMOTION_ID). Always generates cross-
    promo news — a title change in a rival promotion is notable by
    definition. The player hears about it via the cross_promo
    topic in the news feed.

    Distinguishes 'new champion dethroning' from 'vacant title
    claim' (mirrors generate_title_news's logic) — the headline
    and body phrasing differs.
    """
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")

    if not title_id or not fight_id:
        return
    # Only generate cross-promo news for NON-player promotions.
    if promo_id is None or promo_id == _PLAYER_PROMOTION_ID:
        return

    rng = random.Random()

    title_row = conn.execute(
        "SELECT current_champion_fighter_id, champion_since_date, "
        "title_reigns_count, is_vacant FROM titles WHERE title_id=?",
        (title_id,),
    ).fetchone()
    if not title_row:
        return
    champ_id, since_date, reigns_count, _is_vacant_now = title_row
    if not champ_id:
        return  # title is currently vacant — nothing to report

    fight_row = conn.execute(
        "SELECT winner_fighter_id, loser_fighter_id, result_type, "
        "finish_round, finish_time, is_title_fight FROM fights "
        "WHERE fight_id=?",
        (fight_id,),
    ).fetchone()
    if not fight_row:
        return
    winner_id, loser_id, _rt, _fr, _ft, _is_title = fight_row
    if winner_id != champ_id:
        winner_id = champ_id  # defensive — title row is authoritative

    # Vacant claim vs. dethroning.
    is_vacant_claim = (reigns_count is None or reigns_count == 1)

    winner_full = _fighter_full_name(conn, winner_id)
    winner_last = _fighter_last_name(conn, winner_id)
    career_stage = _fighter_career_stage(
        conn, winner_id, rng=rng, current_date=since_date,
    )
    attr_summary = _fighter_descriptor_summary(conn, winner_id, rng=rng)
    rival_promotion = _promotion_name(conn, promo_id)

    if is_vacant_claim:
        # Vacant title claimed — no "dethroning" angle. Use the
        # title_new_champ templates (a "new champion crowned" angle).
        headline = rng.choice(_CROSS_PROMO_HEADLINES_TITLE_NEW_CHAMP).format(
            rival=rival_promotion, winner=winner_last,
        )
    else:
        # Dethronement — the more dramatic angle for cross-promo news.
        # Use the title_new_champ templates (the headline doesn't
        # distinguish defense vs new champ; the body does).
        headline = rng.choice(_CROSS_PROMO_HEADLINES_TITLE_NEW_CHAMP).format(
            rival=rival_promotion, winner=winner_last,
        )

    body = rng.choice(_CROSS_PROMO_BODY_TITLE_NEW_CHAMP).format(
        rival_promotion=rival_promotion,
        winner_full=winner_full,
        winner_art=_article_for(career_stage),
        winner_stage=career_stage,
        winner_attr=attr_summary,
    )

    _write_news_item(
        conn, headline, body, sentiment="positive",
        event_id=event_id, fight_id=fight_id, fighter_id=winner_id,
        promotion_id=promo_id, published_at=since_date, rng=rng,
        topic=CROSS_PROMO_TOPIC,
    )


def _is_big_upset(conn, winner_id, loser_id):
    """Return True if the fight result qualifies as a 'big upset'.

    A big upset is when the winner:
      - Was on a 3+ losing streak (loser was favored by recent form), OR
      - Had 5+ fewer career wins than the loser (loser was favored by
        career record), OR
      - The loser was on a 4+ win streak (loser was clearly favored).

    AND the result is a finish (KO/TKO or submission — a decision
    upset is less notable than a finish upset).
    """
    if winner_id is None or loser_id is None:
        return False

    w_row = conn.execute(
        "SELECT record_wins, loss_streak FROM fighter_career "
        "WHERE fighter_id=?",
        (winner_id,),
    ).fetchone()
    l_row = conn.execute(
        "SELECT record_wins, win_streak FROM fighter_career "
        "WHERE fighter_id=?",
        (loser_id,),
    ).fetchone()
    if not w_row or not l_row:
        return False

    w_wins, w_loss_streak = w_row
    l_wins, l_win_streak = l_row
    w_wins = w_wins or 0
    w_loss_streak = w_loss_streak or 0
    l_wins = l_wins or 0
    l_win_streak = l_win_streak or 0

    is_upset = (
        w_loss_streak >= _BIG_UPSET_LOSS_STREAK_MIN
        or (l_wins - w_wins) >= _BIG_UPSET_RECORD_GAP_MIN
        or l_win_streak >= _BIG_UPSET_WIN_STREAK_LOSER_MIN
    )
    return is_upset


def generate_cross_promo_fight_news(conn, event):
    """Phase C — FIGHT_RESOLVED subscriber for cross-promotion upset news.

    Fires for fights in NON-player promotions (promotion_id !=
    PLAYER_PROMOTION_ID). Only generates cross-promo news for BIG
    UPSETS — underdog with significantly worse record (or on a
    losing streak) wins by KO/submission. Title fights are EXCLUDED
    here (they're covered by the TITLE_CHANGED subscriber above —
    avoids duplicate coverage).

    The result_type must be a finish (KO/TKO or submission) — a
    decision upset is less notable than a finish upset. This keeps
    cross-promo news rare and notable per the brief.
    """
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")
    event_date = event.get("event_date")
    winner_id = event.get("winner_id")
    loser_id = event.get("loser_id")
    result_type = (event.get("result_type") or "").lower()
    is_title_fight = bool(event.get("is_title_fight"))

    # Only non-player promotions.
    if promo_id is None or promo_id == _PLAYER_PROMOTION_ID:
        return
    # Exclude title fights (covered by the TITLE_CHANGED subscriber).
    if is_title_fight:
        return
    # Only finishes (KO/TKO/submission) — decision upsets are less
    # notable for cross-promo news.
    if result_type not in ("ko_tko", "ko", "tko", "submission"):
        return
    if winner_id is None or loser_id is None:
        return

    # Check if the result is a "big upset".
    if not _is_big_upset(conn, winner_id, loser_id):
        return

    rng = random.Random()

    winner_full = _fighter_full_name(conn, winner_id)
    winner_last = _fighter_last_name(conn, winner_id)
    loser_full = _fighter_full_name(conn, loser_id)
    loser_last = _fighter_last_name(conn, loser_id)
    winner_stage = _fighter_career_stage(
        conn, winner_id, rng=rng, current_date=event_date,
    )
    loser_stage = _fighter_career_stage(
        conn, loser_id, rng=rng, current_date=event_date,
    )
    winner_attr = _fighter_descriptor_summary(conn, winner_id, rng=rng)
    loser_attr = _fighter_descriptor_summary(conn, loser_id, rng=rng)
    rival_promotion = _promotion_name(conn, promo_id)

    headline = rng.choice(_CROSS_PROMO_HEADLINES_UPSET).format(
        rival=rival_promotion, winner=winner_last, loser=loser_last,
    )
    body = rng.choice(_CROSS_PROMO_BODY_UPSET).format(
        rival_promotion=rival_promotion,
        winner_full=winner_full,
        winner_art=_article_for(winner_stage),
        winner_stage=winner_stage,
        winner_attr=winner_attr,
        loser_full=loser_full,
        loser_art=_article_for(loser_stage),
        loser_stage=loser_stage,
        loser_attr=loser_attr,
    )

    _write_news_item(
        conn, headline, body, sentiment="neutral",
        event_id=event_id, fight_id=fight_id, fighter_id=winner_id,
        promotion_id=promo_id, published_at=event_date, rng=rng,
        topic=CROSS_PROMO_TOPIC,
    )


# ----------------------------------------------------------------
# REGISTRATION
# ----------------------------------------------------------------

def register_subscribers():
    """Register all news engine subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior
    registrations.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    # Original subscribers (Task 23).
    bus.subscribe(
        Events.FIGHT_RESOLVED, generate_fight_news,
        name="news.generate_fight_news",
    )
    bus.subscribe(
        Events.FIGHT_RESOLVED, generate_injury_news,
        name="news.generate_injury_news",
    )
    bus.subscribe(
        Events.TITLE_CHANGED, generate_title_news,
        name="news.generate_title_news",
    )
    # A11a — memory resurfacing: ADDITIONAL subscriber on TITLE_CHANGED.
    # Writes a torch-passing news item when the new champion has a
    # 'successor' link in fighter_memory_links (i.e. they're the regen
    # replacement of a retired legend). Additive to generate_title_news
    # — both fire on TITLE_CHANGED, both write their own news item.
    bus.subscribe(
        Events.TITLE_CHANGED, generate_memory_resurfacing_news,
        name="news.generate_memory_resurfacing_news",
    )
    bus.subscribe(
        Events.TICK_ADVANCED, generate_retirement_news,
        name="news.generate_retirement_news",
    )
    # A5 — fill the unsubscribed event types. Each subscriber writes
    # a single news_engine item per event with a voice-layer-driven
    # headline + body.
    bus.subscribe(
        Events.CAMP_COMPLETED, generate_camp_news,
        name="news.generate_camp_news",
    )
    bus.subscribe(
        Events.CAMP_INJURY, generate_camp_injury_news,
        name="news.generate_camp_injury_news",
    )
    bus.subscribe(
        Events.FIGHT_CANCELLED, generate_fight_cancelled_news,
        name="news.generate_fight_cancelled_news",
    )
    bus.subscribe(
        Events.INJURY_CREATED, generate_injury_created_news,
        name="news.generate_injury_created_news",
    )
    bus.subscribe(
        Events.INJURY_RECOVERED, generate_injury_recovered_news,
        name="news.generate_injury_recovered_news",
    )
    bus.subscribe(
        Events.FIGHTER_RETIRED, generate_fighter_retired_news,
        name="news.generate_fighter_retired_news",
    )
    bus.subscribe(
        Events.FIGHTER_SIGNED, generate_fighter_signed_news,
        name="news.generate_fighter_signed_news",
    )
    bus.subscribe(
        Events.FIGHTER_GENERATED, generate_fighter_generated_news,
        name="news.generate_fighter_generated_news",
    )
    bus.subscribe(
        Events.CONTRACT_EXPIRED, generate_contract_expired_news,
        name="news.generate_contract_expired_news",
    )
    bus.subscribe(
        Events.SCOUT_REPORT_GENERATED, generate_scout_report_news,
        name="news.generate_scout_report_news",
    )
    bus.subscribe(
        Events.WEIGHT_CUT_COMPLETED, generate_weight_cut_news,
        name="news.generate_weight_cut_news",
    )
    bus.subscribe(
        Events.EVENT_COMPLETED, generate_event_recap_news,
        name="news.generate_event_recap_news",
    )
    # Phase B — suspension news (polling subscriber on TICK_ADVANCED).
    # Scans the suspensions table for new active suspensions (writes
    # creation news) and newly-cleared suspensions (writes clearance
    # news). Dedup via hidden [suspension_id=N] marker in the body.
    # Mirrors the generate_retirement_news polling pattern.
    bus.subscribe(
        Events.TICK_ADVANCED, generate_suspension_news,
        name="news.generate_suspension_news",
    )
    # A6 — news pruning (weekly tick).
    bus.subscribe(
        Events.TICK_ADVANCED, prune_old_news,
        name="news.prune_old_news",
    )
    # Phase C — upcoming event hype news (weekly tick). Generates up
    # to 2 hype news items per scheduled event in the next 7 days.
    # 3 hype types (card_announce / weigh_in / training); RNG picks
    # 2 of 3 per event. Voice-layer-driven per §14.
    bus.subscribe(
        Events.TICK_ADVANCED, generate_event_hype_news,
        name="news.generate_event_hype_news",
    )
    # Phase C — cross-promotion news. Title changes in rival
    # promotions always generate cross-promo news (the player should
    # hear about a new champion in a rival room). Big upsets in rival
    # promotions (underdog with worse record + KO/submission finish)
    # also generate cross-promo news. Title fights are excluded from
    # the FIGHT_RESOLVED subscriber (covered by TITLE_CHANGED).
    bus.subscribe(
        Events.TITLE_CHANGED, generate_cross_promo_title_news,
        name="news.generate_cross_promo_title_news",
    )
    bus.subscribe(
        Events.FIGHT_RESOLVED, generate_cross_promo_fight_news,
        name="news.generate_cross_promo_fight_news",
    )
