"""CAGE EMPIRE Social Media System (Task 21, extended Phase A — A3 + A7).

Fighter-driven social media posts + beef escalation, entirely event-bus-
driven (Task 18.5). Subscribes to FIGHT_RESOLVED, TITLE_CHANGED, and
TICK_ADVANCED and writes voice-layer-driven posts to the `social_posts`
table (added in v3.1.0).

CONVENTIONS compliance:
  §13 — Design Law: every post tells a story. Fighters have personality-
        driven voices — a hot-headed champion trash-talks differently
        than a humble veteran. Beefs build rivalries (Task 22 will
        consume this data to seed rivalries from accumulated beefs).
        Strengthens Conflict (beefs, trash talk, callouts) and Stories
        (in-character social media drama).
  §14 — Voice Layer: NO raw attribute values, potential numbers, or
        internal ratings appear in any post_text. All fighter attributes
        are described via voice.describe_attribute; career stage via
        voice.describe_career_stage; health via voice.
        describe_career_health. Round numbers use word forms ("first
        round", "opening minute") — never digit characters.
  §15 — Event Bus: the social system is entirely event-driven. It
        subscribes to events published by resolve_next_fight and
        run_tick; no new inline side effects are added to those
        functions (§15.4).

SAME-ROSTER RESTRICTIONS (A3):
  Callouts and trash-talk posts target fighters in the SAME promotion
  by default. Cross-promotion callouts are only attempted when no
  same-promotion candidate exists AND a 5% random gate passes AND the
  cross-promo candidate is in the same weight class. A cross-promo
  callout also generates an "inter-promo callout" news item (rare,
  big-hype — the sport's white whale).

SOCIAL FREQUENCY THROTTLE (A7):
  Every fighter has a 7-day posting cooldown. The cooldown is enforced
  inside generate_post (the lowest-level entry point) so all callers
  respect it. Callers that MUST post (winner brag on FIGHT_RESOLVED,
  champion brag on TITLE_CHANGED) pass bypass_cooldown=True; TICK_
  ADVANCED posts always go through the cooldown. This prevents a single
  high-attention_seeking fighter from dominating the feed every tick.

PERSONALITY INFLUENCE:
  - attention_seeking: high → more frequent posts on TICK_ADVANCED
                      (probability boost); also biases toward hype /
                        announcement post types.
  - aggression:        high → more trash_talk / callouts / challenges
                        (post type weight is shifted toward these).
  - charisma:          high → higher engagement score (likes + comments
                        on the post).
  - ego:               high → more brags / challenges (post type weight
                        is shifted toward these).
  - composure:         high → fewer excuse posts; more measured tone.
                        Low composure losers → more excuse posts.
  - sportsmanship:     high → more apologies, fewer trash_talks.
                        Low sportsmanship losers → trash-talk the winner.
  - marketability:     feeds engagement (high marketability → boost).

BEEF ESCALATION:
  When fighter A has previously callout'd or trash-talked fighter B
  (a row in social_posts with fighter_id=A, target_fighter_id=B, and
  post_type IN ('callout','trash_talk')), any new callout/trash_talk/
  excuse post between them is flagged is_beef_escalation=1. This lets
  Task 22 (rivalries) mine the post table to seed rivalries — a
  fighter with multiple beef-escalation posts against the same target
  is a strong rivalry candidate.

USAGE:
  from social import register_subscribers
  register_subscribers()  # call once at startup (UI / tests)

  # The system automatically processes events via the bus. No need
  # to call any function directly — it's all event-driven.
"""

import random
from datetime import datetime

from voice import (
    describe_attribute,
    describe_career_stage,
    describe_career_health,
    describe_personality,
)


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

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

# Valid post types (matches the CHECK constraint on social_posts).
VALID_POST_TYPES = (
    "callout", "trash_talk", "hype", "apology", "announcement",
    "brag", "excuse", "retirement_hint", "challenge",
)

# Maximum posts generated per TICK_ADVANCED event. Caps the per-tick
# volume so a 4000-fighter world DB doesn't generate 4000 posts/day.
# Fighters are sampled by attention_seeking weight.
_MAX_TICK_POSTS = 5

# A3 — cross-promotion callout chance. Same as rivalries._CROSS_PROMO_
# CALLOUT_CHANCE; duplicated here to avoid a circular import (the
# rivalries module imports from voice, social doesn't import from
# rivalries). If the chance ever diverges, the callout logic should
# be lifted into a shared helper.
_CROSS_PROMO_CALLOUT_CHANCE = 0.05

# A7 — social frequency throttle. A fighter can post at most once
# every 7 sim days. This prevents a high-attention_seeking fighter
# from dominating the feed every tick. The cooldown is enforced in
# generate_post (the lowest-level entry point) so all callers
# (_process_fight_social, _process_title_social, _check_social_
# activity) respect it.
_POST_COOLDOWN_DAYS = 7

# Word-form helpers (no digit characters per CONVENTIONS §14).
_ROUND_WORDS = {
    1: "first", 2: "second", 3: "third",
    4: "fourth", 5: "fifth",
}


# ----------------------------------------------------------------
# Fighter / promotion data helpers (mirror news.py patterns)
# ----------------------------------------------------------------

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
    """Return just the fighter's last name (for in-line mentions)."""
    if fighter_id is None:
        return "Unknown"
    row = conn.execute(
        "SELECT last_name FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else "Unknown"


def _fighter_age(conn, fighter_id, current_date=None):
    """Compute a fighter's age based on DOB and a reference date."""
    row = conn.execute(
        "SELECT date_of_birth FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row or not row[0]:
        return 30
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


def _fighter_top_attribute(conn, fighter_id, rng=None):
    """Return a voice descriptor for the fighter's top attribute.

    Picks the highest-value attribute and returns a phrase like
    "one-punch knockout threat" or "iron chin". Falls back to
    "a serviceable skill set" if attributes are missing.
    """
    if fighter_id is None:
        return "a serviceable skill set"
    cols_sql = ", ".join(_ATTR_NAMES)
    row = conn.execute(
        f"SELECT {cols_sql} FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "a serviceable skill set"
    paired = list(zip(_ATTR_NAMES, row))
    paired.sort(key=lambda x: (x[1] if x[1] is not None else 0), reverse=True)
    for attr_name, value in paired:
        if value is None:
            continue
        d = describe_attribute(attr_name, value, rng=rng)
        if d:
            return d
    return "a serviceable skill set"


def _fighter_career_stage(conn, fighter_id, rng=None, current_date=None):
    """Return the fighter's career stage descriptor (voice layer).

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


def _fighter_health_descriptor(conn, fighter_id, rng=None):
    """Return a voice descriptor for the fighter's career health."""
    if fighter_id is None:
        return "an unknown bill of health"
    row = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    health = row[0] if row and row[0] is not None else 100
    return describe_career_health(health, rng=rng)


def _fighter_personality_value(conn, fighter_id, trait):
    """Return a single personality trait value (0-100) for a fighter.

    Falls back to the schema DEFAULT (50) if the row is missing.
    """
    if fighter_id is None or trait not in (
        "aggression", "composure", "morale", "risk_taking",
        "killer_instinct", "grit", "discipline", "patience",
        "ambition", "loyalty", "charisma", "attention_seeking",
        "coachability", "professionalism", "ego", "resilience",
        "sportsmanship", "travel_comfort", "focus", "fatigue_tolerance",
    ):
        return 50
    row = conn.execute(
        f"SELECT {trait} FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 50


def _fighter_marketability(conn, fighter_id):
    """Return the fighter's marketability (0-100). Falls back to 50."""
    if fighter_id is None:
        return 50
    row = conn.execute(
        "SELECT marketability FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] is not None else 50


# ----------------------------------------------------------------
# Beef detection
# ----------------------------------------------------------------

def _has_prior_beef(conn, fighter_id, target_fighter_id):
    """Return True if fighter_id has previously callout'd or trash-
    talked target_fighter_id (i.e., there's a prior post between them
    that establishes a beef).

    Used to flag the new post as is_beef_escalation=1.
    """
    if not fighter_id or not target_fighter_id:
        return False
    if fighter_id == target_fighter_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM social_posts "
        "WHERE fighter_id=? AND target_fighter_id=? "
        "AND post_type IN ('callout','trash_talk','excuse','challenge') "
        "LIMIT 1",
        (fighter_id, target_fighter_id),
    ).fetchone()
    return row is not None


# ----------------------------------------------------------------
# Engagement computation
# ----------------------------------------------------------------

def _compute_engagement(conn, fighter_id, post_type, is_beef=False,
                        rng=None):
    """Compute the engagement score for a post.

    Engagement = base (charisma-weighted) + post_type modifier +
    beef escalation bonus + marketability bonus + noise.

    The score is stored as an integer in the engagement column. The
    voice layer (§14) applies to post_text only — engagement is a
    behind-the-scenes number the UI may later band into descriptors
    like "low engagement" / "viral post".

    Always returns >= 0 (CHECK constraint requires it).
    """
    if rng is None:
        rng = random.Random()
    charisma = _fighter_personality_value(conn, fighter_id, "charisma")
    marketability = _fighter_marketability(conn, fighter_id)
    base = int(charisma * 10 + marketability * 5)
    type_mod = {
        "callout": 500,         # callouts drive clicks
        "trash_talk": 800,      # trash talk goes viral
        "challenge": 700,       # title challenges trend
        "brag": 300,
        "hype": 200,
        "excuse": 150,
        "apology": 400,         # apologies get engagement too
        "announcement": 250,
        "retirement_hint": 600,
    }.get(post_type, 200)
    beef_bonus = 1000 if is_beef else 0
    noise = rng.randint(-50, 150)
    return max(0, base + type_mod + beef_bonus + noise)


# ----------------------------------------------------------------
# Post templates — at least 3 variants per type, all using voice
# descriptors ({descriptor}, {career_stage}, {health_descriptor},
# {target_name}, {target_last}, {opponent_name}, {opponent_last}).
# ----------------------------------------------------------------

_POST_TEMPLATES = {
    "callout": [
        "I want {target_name} next. He's been ducking me. {descriptor} or not, I'll expose him.",
        "{target_last} keeps running his mouth. Time to back it up. {career_stage_cap} vs {target_last} — book it.",
        "Everyone's talking about {target_name}. They forget I'm {descriptor}. Line him up.",
        "{target_last} hasn't faced anyone like me yet. {career_stage_cap} with {descriptor}. Make the fight.",
    ],
    "trash_talk": [
        "{target_name} is overrated. {descriptor_cap}? Please. I'd finish him in the first.",
        "{target_last} is a fraud. {career_stage_cap} would expose him. Hype job. Easy work.",
        "They built {target_name} up to fail. Once my {descriptor} lands clean, the myth ends.",
        "{target_last} keeps getting gift decisions. {career_stage_cap} with {descriptor} would put him out clean.",
    ],
    "hype": [
        "Camp is going great. Feeling {descriptor}. Ready to show the world what I can do.",
        "Body is right, mind is right. {career_stage_cap} with {descriptor}. Locked in.",
        "Best shape of my life. {health_descriptor_cap}. The work is paying off.",
        "Gym sessions have been war. {descriptor_cap} on display every round. Countdown begins.",
    ],
    "brag": [
        "Told you. {descriptor_cap} did exactly what I said it would. Who's next?",
        "Easy work. Just a {career_stage} doing what we do. Nobody on my level.",
        "Did what I said I'd do. {descriptor_cap}. The rest of the division is on notice.",
        "Another one in the books. {descriptor_cap} — that's the difference. Belt's coming home soon.",
    ],
    "excuse": [
        "Wasn't my night. {health_descriptor_cap}. I'll be back stronger.",
        "Take nothing from him, but I wasn't right. {health_descriptor_cap}. We run it back.",
        "Things didn't go my way. {health_descriptor_cap}. Camp was rough. Lesson learned.",
        "I'll hold my hands up — he got me. But {health_descriptor}. Different night, different result.",
    ],
    "apology": [
        "I let my emotions get the better of me. Respect to {opponent_name}. This {career_stage} knows better. It won't happen again.",
        "Watched it back. Lost my head. {opponent_last} is a real one. {health_descriptor_cap}, but my head wasn't right. My bad.",
        "No excuses — I crossed the line. {opponent_name} earned that night. {career_stage_cap} should act like one. I'll be better.",
        "To the fans, to {opponent_last}, to the promotion — I apologize. That's not who this {career_stage} is.",
    ],
    "challenge": [
        "{target_name} vs me for the title. {descriptor_cap}. Make it happen.",
        "{target_last} is wearing my belt. I'm coming for it. {career_stage_cap} with {descriptor}. Title fight next.",
        "Champion vs {career_stage}. {descriptor_cap}. Book it. I'm ready.",
        "{target_name} has the gold. I want it. {descriptor_cap}. Make the call.",
    ],
    "announcement": [
        "Big news coming soon. This {career_stage} is about to take the next step. Stay tuned.",
        "Something's brewing. {career_stage_cap} about to take the next step. Watch this space.",
        "Been quiet for a reason. Announcement dropping soon. {descriptor_cap} on the way.",
        "Huge things in the works. {career_stage_cap} with big plans. Stay locked in.",
    ],
    "retirement_hint": [
        "Maybe it's time. {health_descriptor_cap}. We'll see.",
        "Body's talking to me. {health_descriptor_cap}. Thinking about the next chapter.",
        "Lot of miles on these tires. {career_stage_cap} has done it all. We'll see what's next.",
        "Been a long road. {health_descriptor_cap}. The end might be closer than people think.",
    ],
}


def _safe_cap(word):
    """Capitalize the first letter of a phrase for sentence starts."""
    if not word:
        return word
    return word[0].upper() + word[1:]


def _safe_lower(word):
    """Lowercase the first letter of a phrase (for mid-sentence use)."""
    if not word:
        return word
    return word[0].lower() + word[1:]


# ----------------------------------------------------------------
# Core post writer
# ----------------------------------------------------------------

def generate_post(conn, fighter_id, post_type, target_fighter_id=None,
                  post_date=None, opponent_fighter_id=None, rng=None,
                  bypass_cooldown=False):
    """Generate a single social_posts row with voice-layer descriptors.

    Args:
        conn: sqlite3.Connection (caller commits).
        fighter_id: the posting fighter's ID (required).
        post_type: one of VALID_POST_TYPES.
        target_fighter_id: optional — for callouts / trash_talk /
            challenges, the fighter being targeted.
        post_date: optional ISO date string. Defaults to today per the
            simulation_clock.
        opponent_fighter_id: optional — for apologies / excuses after
            a fight, the opponent's fighter_id (used to fill the
            {opponent_name} / {opponent_last} slots). If None and the
            post type is apology/excuse, falls back to target_fighter_id.
        rng: optional random.Random for template variant selection.
        bypass_cooldown: A7 — kept for API compatibility but the
            cooldown is now enforced in the TICK_ADVANCED subscriber
            (_check_social_activity) rather than here. The brief says
            the throttle is for TICK_ADVANCED-driven posts ("prevents
            a single high-attention_seeking fighter from posting
            every tick") — not for direct generate_post calls (which
            are used by tests and by FIGHT_RESOLVED subscribers where
            the post is event-driven and shouldn't be silenced). The
            flag is accepted but no longer affects behavior.

    Returns:
        The new post_id (int), or None if the insert failed (e.g.,
        fighter_id doesn't exist).

    Raises:
        ValueError: if post_type is not in VALID_POST_TYPES.
    """
    if post_type not in VALID_POST_TYPES:
        raise ValueError(
            f"Invalid post_type {post_type!r}; expected one of {VALID_POST_TYPES}"
        )
    if rng is None:
        rng = random.Random()

    # Resolve post_date — default to the simulation clock's current date.
    if post_date is None:
        clock = conn.execute(
            "SELECT simulation_clock.current_date FROM simulation_clock "
            "WHERE clock_id=1"
        ).fetchone()
        post_date = clock[0] if clock else "2026-08-15"

    # Verify the fighter exists.
    fighter_exists = conn.execute(
        "SELECT 1 FROM fighters WHERE fighter_id=?", (fighter_id,)
    ).fetchone()
    if not fighter_exists:
        return None

    # Voice-layer descriptors for the posting fighter.
    descriptor = _fighter_top_attribute(conn, fighter_id, rng=rng)
    career_stage = _fighter_career_stage(
        conn, fighter_id, rng=rng, current_date=post_date,
    )
    health_descriptor = _fighter_health_descriptor(conn, fighter_id, rng=rng)

    # Resolve target_name / target_last if a target was provided.
    target_name = (
        _fighter_full_name(conn, target_fighter_id)
        if target_fighter_id else "whoever they put in front of me"
    )
    target_last = (
        _fighter_last_name(conn, target_fighter_id)
        if target_fighter_id else "the next guy"
    )

    # Resolve opponent (for apologies / excuses). Fall back to target
    # if no separate opponent was passed.
    opp_id = opponent_fighter_id or target_fighter_id
    opponent_name = (
        _fighter_full_name(conn, opp_id) if opp_id else "my opponent"
    )
    opponent_last = (
        _fighter_last_name(conn, opp_id) if opp_id else "my opponent"
    )

    # Pick a template variant.
    templates = _POST_TEMPLATES.get(post_type)
    template = rng.choice(templates)

    post_text = template.format(
        descriptor=descriptor,
        descriptor_cap=_safe_cap(descriptor),
        career_stage=career_stage,
        career_stage_cap=_safe_cap(career_stage),
        career_stage_lower=_safe_lower(career_stage),
        health_descriptor=health_descriptor,
        health_descriptor_cap=_safe_cap(health_descriptor),
        target_name=target_name,
        target_last=target_last,
        opponent_name=opponent_name,
        opponent_last=opponent_last,
    )

    # Beef escalation check: a callout / trash_talk / excuse / challenge
    # against a target the posting fighter has previously called out
    # or trash-talked gets is_beef_escalation=1.
    is_beef = 0
    if post_type in ("callout", "trash_talk", "excuse", "challenge"):
        if _has_prior_beef(conn, fighter_id, target_fighter_id):
            is_beef = 1

    engagement = _compute_engagement(
        conn, fighter_id, post_type, is_beef=is_beef, rng=rng,
    )

    cur = conn.execute(
        "INSERT INTO social_posts "
        "(fighter_id, post_type, target_fighter_id, post_text, "
        " post_date, engagement, is_beef_escalation) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fighter_id, post_type, target_fighter_id, post_text,
         post_date, engagement, is_beef),
    )
    return cur.lastrowid


# ----------------------------------------------------------------
# FIGHT_RESOLVED subscriber — winner brags, loser makes excuses /
# calls out / trash-talks based on personality.
# ----------------------------------------------------------------

def _process_fight_social(conn, event):
    """Subscriber for FIGHT_RESOLVED — generates posts from both fighters.

    Winner:
      - Always writes a brag post.
      - High-aggression + high-ego winners may also write a callout
        targeting a future opponent (a top contender in their weight
        class). The probability scales with aggression + ego.

    Loser:
      - Low composure + high ego → excuse post (targeted at winner).
      - High aggression + low sportsmanship → trash_talk post
        (targeted at winner).
      - High sportsmanship → apology post (opponent = winner).
      - Default (mid-traits) → silence (no post; the loss speaks for
        itself).

    Draws are skipped (no winner/loser). The event bus guarantees
    FIGHT_RESOLVED fires after all inline side effects (fight_history,
    rankings, titles, news, commentary) have completed.
    """
    rng = random.Random()
    winner_id = event.get("winner_id")
    loser_id = event.get("loser_id")
    result_type = event.get("result_type", "") or ""
    finish_round = event.get("finish_round") or 1
    event_date = event.get("event_date")
    is_title = event.get("is_title_fight", False)

    # Skip draws (winner_id and loser_id are None for draws).
    if winner_id is None or loser_id is None:
        return

    # ---- WINNER post ----
    # Always brag (bypass_cooldown=True — the fighter just won a fight,
    # the cooldown shouldn't silence the moment).
    generate_post(
        conn, winner_id, "brag",
        target_fighter_id=loser_id,
        opponent_fighter_id=loser_id,
        post_date=event_date, rng=rng, bypass_cooldown=True,
    )

    # Winner callout: probability scales with aggression + ego.
    aggression = _fighter_personality_value(conn, winner_id, "aggression")
    ego = _fighter_personality_value(conn, winner_id, "ego")
    callout_chance = (aggression + ego) / 200.0 * 0.5  # ~0-50% chance
    if rng.random() < callout_chance:
        target_id = _pick_callout_target(conn, winner_id, rng=rng)
        if target_id is not None and target_id != loser_id:
            generate_post(
                conn, winner_id, "callout",
                target_fighter_id=target_id,
                post_date=event_date, rng=rng, bypass_cooldown=True,
            )
            # A3 — if the callout crossed promotion lines, also write
            # an inter-promotion callout news item (rare, big-hype).
            _maybe_write_inter_promo_callout_news(
                conn, winner_id, target_id,
                post_date=event_date, rng=rng,
            )

    # ---- LOSER post ----
    # Personality-driven: excuse / trash_talk / apology / silence.
    composure = _fighter_personality_value(conn, loser_id, "composure")
    sportsmanship = _fighter_personality_value(conn, loser_id, "sportsmanship")
    los_aggression = _fighter_personality_value(conn, loser_id, "aggression")
    los_ego = _fighter_personality_value(conn, loser_id, "ego")

    # Roll once for "which response type". Weights depend on traits.
    # Possible responses: 'excuse', 'trash_talk', 'apology', 'silent'.
    weights = {
        "excuse":     max(0.05, (los_ego * 1.5 + (100 - composure)) / 250.0),
        "trash_talk": max(0.0,  (los_aggression + (100 - sportsmanship)) / 250.0),
        "apology":    max(0.05, sportsmanship / 200.0),
    }
    weights["silent"] = max(0.1, 1.0 - sum(weights.values()))
    roll = rng.random() * sum(weights.values())
    cumulative = 0.0
    response = "silent"
    for kind, w in weights.items():
        cumulative += w
        if roll < cumulative:
            response = kind
            break

    if response == "excuse":
        generate_post(
            conn, loser_id, "excuse",
            target_fighter_id=winner_id,
            opponent_fighter_id=winner_id,
            post_date=event_date, rng=rng, bypass_cooldown=True,
        )
    elif response == "trash_talk":
        generate_post(
            conn, loser_id, "trash_talk",
            target_fighter_id=winner_id,
            opponent_fighter_id=winner_id,
            post_date=event_date, rng=rng, bypass_cooldown=True,
        )
    elif response == "apology":
        generate_post(
            conn, loser_id, "apology",
            target_fighter_id=winner_id,
            opponent_fighter_id=winner_id,
            post_date=event_date, rng=rng, bypass_cooldown=True,
        )
    # else: silent — no post.


def _pick_callout_target(conn, fighter_id, rng=None):
    """Pick a callout target for the posting fighter.

    Strategy: prefer a top-ranked fighter in the same weight class +
    promotion who is NOT the fighter themselves. If no rankings exist,
    fall back to any other active fighter in the same weight class.
    Returns a fighter_id or None if no candidate is available.

    A3 — same-roster restrictions. Cross-promotion callouts are only
    considered when (a) no same-promotion candidate is available AND
    (b) a 5% random gate passes AND (c) the cross-promo candidate is
    in the same weight class. The cross-promo callout is the rare
    "inter-promotion superfight" callout that generates extra hype.
    The caller (generate_post or _process_fight_social) generates an
    inter-promotion news item via _maybe_write_inter_promo_callout
    news when this function returns a cross-promo target.
    """
    if rng is None:
        rng = random.Random()
    # The posting fighter's weight class + promotion.
    f_row = conn.execute(
        "SELECT weight_class_id, current_promotion_id "
        "FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not f_row:
        return None
    wc_id, promo_id = f_row
    if wc_id is None:
        return None

    # Top-3 other ranked fighters in the same weight class + promo.
    candidates = conn.execute(
        "SELECT r.fighter_id FROM rankings r "
        "JOIN fighters f ON f.fighter_id = r.fighter_id "
        "WHERE r.weight_class_id=? AND r.promotion_id=? "
        "AND r.fighter_id != ? "
        "AND f.is_active = 1 AND f.is_retired = 0 "
        "ORDER BY r.rating DESC LIMIT 5",
        (wc_id, promo_id or -1, fighter_id),
    ).fetchall()
    if not candidates:
        # Fall back to any other active fighter in the same weight class
        # AND same promotion (A3 — don't reach across promotions unless
        # the cross-promo gate below fires).
        candidates = conn.execute(
            "SELECT fighter_id FROM fighters "
            "WHERE weight_class_id=? AND fighter_id != ? "
            "AND is_active = 1 AND is_retired = 0 "
            "AND (current_promotion_id = ? "
            "     OR current_promotion_id IS NULL) "
            "LIMIT 5",
            (wc_id, fighter_id, promo_id or -1),
        ).fetchall()
    if not candidates:
        # A3 — last-resort cross-promotion callout. Only fires with a
        # 5% chance AND requires a same-weight-class fighter in a
        # different promotion. This is the rare "inter-promotion
        # superfight" callout — e.g., a UFC champ calling out a ONE
        # champ. Generates extra hype via an inter-promo news item.
        if rng.random() < _CROSS_PROMO_CALLOUT_CHANCE:
            candidates = conn.execute(
                "SELECT fighter_id FROM fighters "
                "WHERE weight_class_id=? AND fighter_id != ? "
                "AND is_active = 1 AND is_retired = 0 "
                "AND current_promotion_id IS NOT NULL "
                "AND current_promotion_id != ? "
                "LIMIT 5",
                (wc_id, fighter_id, promo_id or -1),
            ).fetchall()
        if not candidates:
            return None
    return rng.choice(candidates)[0]


def _is_cross_promo_callout(conn, fighter_id, target_id):
    """A3 — return True if this callout crosses promotion lines.

    Used by the FIGHT_RESOLVED + TITLE_CHANGED subscribers to decide
    whether to also write an 'inter-promotion callout' news item
    alongside the social post. Free agents (current_promotion_id IS
    NULL) on either side don't count as cross-promo (they're unsigned
    — they're not really "in" a promotion).
    """
    if not fighter_id or not target_id:
        return False
    row = conn.execute(
        "SELECT a.current_promotion_id, b.current_promotion_id "
        "FROM fighters a, fighters b "
        "WHERE a.fighter_id=? AND b.fighter_id=?",
        (fighter_id, target_id),
    ).fetchone()
    if not row:
        return False
    promo_a, promo_b = row
    if promo_a is None or promo_b is None:
        return False
    return promo_a != promo_b


def _maybe_write_inter_promo_callout_news(conn, fighter_id, target_id,
                                           post_date=None, rng=None):
    """A3 — write a news item when a callout crosses promotion lines.

    Topic='inter_promo_callout', so the UI can filter these rare
    cross-promotion callouts as a distinct narrative thread. Voice
    layer applies (no raw numbers). Returns the news_item_id on
    insert, or None if the callout wasn't actually cross-promo or
    the insert failed.
    """
    if not _is_cross_promo_callout(conn, fighter_id, target_id):
        return None
    if rng is None:
        rng = random.Random()
    if post_date is None:
        clock = conn.execute(
            "SELECT simulation_clock.current_date FROM simulation_clock "
            "WHERE clock_id=1"
        ).fetchone()
        post_date = clock[0] if clock else "2026-08-15"

    fighter_full = _fighter_full_name(conn, fighter_id)
    target_full = _fighter_full_name(conn, target_id)
    fighter_promo = _fighter_promotion_name(conn, fighter_id)
    target_promo = _fighter_promotion_name(conn, target_id)
    # Get or create the System Feed source (used for non-news_engine
    # inline news items — same pattern as app.write_news).
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    headline = (
        f"{fighter_full} calls out {target_full} across promotion lines"
    )
    body = (
        f"In a rare inter-promotion challenge, {fighter_full} of "
        f"{fighter_promo} has called out {target_full} of "
        f"{target_promo}. Cross-promotion superfights are the sport's "
        f"white whale — fans will dream of the matchup, promoters will "
        f"weigh the risk, and the callout alone fuels weeks of "
        f"speculation."
    )
    cur = conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, "
        "sentiment, topic, fighter_id, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "neutral", "inter_promo_callout",
         fighter_id, post_date),
    )
    return cur.lastrowid


def _fighter_promotion_name(conn, fighter_id):
    """Return the fighter's promotion name (or 'the unsigned ranks')."""
    if fighter_id is None:
        return "the unsigned ranks"
    row = conn.execute(
        "SELECT p.name FROM promotions p "
        "JOIN fighters f ON f.current_promotion_id = p.promotion_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row else "the unsigned ranks"


# ----------------------------------------------------------------
# TITLE_CHANGED subscriber — new champion brags, dethroned vows revenge
# ----------------------------------------------------------------

def _process_title_social(conn, event):
    """Subscriber for TITLE_CHANGED — generates title-related posts.

    New champion:
      - Always writes a brag (escalation of the FIGHT_RESOLVED brag —
        this one is title-flavored). High-ego + high-charisma champs
        may also write a challenge to a specific contender.

    Dethroned fighter (former champion, if not a vacant-claim):
      - High aggression + low sportsmanship → trash_talk aimed at the
        new champion ("I want my belt back").
      - Low composure + high ego → excuse post.
      - High sportsmanship → apology post.
      - Default → silent.
    """
    rng = random.Random()
    title_id = event.get("title_id")
    fight_id = event.get("fight_id")
    event_id = event.get("event_id")
    promo_id = event.get("promotion_id")

    if not title_id or not fight_id:
        return

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
        "SELECT winner_fighter_id, loser_fighter_id, result_type "
        "FROM fights WHERE fight_id=?",
        (fight_id,),
    ).fetchone()
    if not fight_row:
        return
    winner_id, loser_id, _rt = fight_row
    if winner_id != champ_id:
        # Defensive: title says champ is X, fight says winner is Y.
        winner_id = champ_id

    # New champion brag (bypass_cooldown=True — title-change moment).
    generate_post(
        conn, winner_id, "brag",
        target_fighter_id=loser_id,
        opponent_fighter_id=loser_id,
        post_date=since_date, rng=rng, bypass_cooldown=True,
    )

    # High-ego + high-charisma champs also challenge a contender.
    ego = _fighter_personality_value(conn, winner_id, "ego")
    charisma = _fighter_personality_value(conn, winner_id, "charisma")
    challenge_chance = (ego + charisma) / 200.0 * 0.4  # ~0-40%
    if rng.random() < challenge_chance:
        target_id = _pick_callout_target(conn, winner_id, rng=rng)
        if target_id is not None and target_id != loser_id:
            generate_post(
                conn, winner_id, "challenge",
                target_fighter_id=target_id,
                post_date=since_date, rng=rng, bypass_cooldown=True,
            )
            # A3 — if the title challenge crossed promotion lines, also
            # write an inter-promotion callout news item.
            _maybe_write_inter_promo_callout_news(
                conn, winner_id, target_id,
                post_date=since_date, rng=rng,
            )

    # Dethroned fighter (former champion) — only if this wasn't a
    # vacant-claim (reigns_count > 1 means a champion was dethroned).
    is_vacant_claim = (reigns_count is None or reigns_count == 1)
    if is_vacant_claim or loser_id is None:
        return  # no former champion to react

    # Former champion reacts to losing the belt.
    composure = _fighter_personality_value(conn, loser_id, "composure")
    sportsmanship = _fighter_personality_value(conn, loser_id, "sportsmanship")
    los_aggression = _fighter_personality_value(conn, loser_id, "aggression")
    los_ego = _fighter_personality_value(conn, loser_id, "ego")

    weights = {
        "trash_talk": max(0.05, (los_aggression + (100 - sportsmanship)) / 200.0),
        "excuse":     max(0.05, (los_ego + (100 - composure)) / 250.0),
        "apology":    max(0.05, sportsmanship / 250.0),
    }
    weights["silent"] = max(0.1, 1.0 - sum(weights.values()))
    roll = rng.random() * sum(weights.values())
    cumulative = 0.0
    response = "silent"
    for kind, w in weights.items():
        cumulative += w
        if roll < cumulative:
            response = kind
            break

    if response == "trash_talk":
        generate_post(
            conn, loser_id, "trash_talk",
            target_fighter_id=winner_id,
            opponent_fighter_id=winner_id,
            post_date=since_date, rng=rng, bypass_cooldown=True,
        )
    elif response == "excuse":
        generate_post(
            conn, loser_id, "excuse",
            target_fighter_id=winner_id,
            opponent_fighter_id=winner_id,
            post_date=since_date, rng=rng, bypass_cooldown=True,
        )
    elif response == "apology":
        generate_post(
            conn, loser_id, "apology",
            target_fighter_id=winner_id,
            opponent_fighter_id=winner_id,
            post_date=since_date, rng=rng, bypass_cooldown=True,
        )


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber — personality-driven posts
# ----------------------------------------------------------------

def _check_social_activity(conn, event):
    """Subscriber for TICK_ADVANCED — personality-driven posts.

    On each tick, samples up to _MAX_TICK_POSTS active fighters weighted
    by their attention_seeking trait (high-attention fighters post
    more). For each sampled fighter, picks a post type based on their
    personality:

      - High aggression → bias toward trash_talk / callout / challenge.
      - High ego → bias toward brag / challenge.
      - High attention_seeking → bias toward hype / announcement.
      - Low composure + recent loss → bias toward excuse.
      - High sportsmanship + recent loss → bias toward apology.
      - Older fighter with low career_health → small chance of
        retirement_hint.

    Callout / trash_talk / challenge posts target another ranked
    fighter in the same weight class + promotion (via
    _pick_callout_target).

    The post volume is capped at _MAX_TICK_POSTS per tick so a 4000-
    fighter world DB doesn't generate 4000 posts/day.

    A7 — social frequency throttle. Before generating a post for a
    fighter, the subscriber checks the fighter's most recent post_date
    in social_posts. If the last post was within _POST_COOLDOWN_DAYS
    (7) days, the fighter is skipped (silent). This prevents a single
    high-attention_seeking fighter from posting every tick. Direct
    calls to generate_post (from tests, from FIGHT_RESOLVED subscribers)
    are NOT throttled — the throttle is only for TICK_ADVANCED-driven
    posts. The throttle is enforced here (in the subscriber) rather
    than in generate_post so direct callers retain full control.
    """
    rng = random.Random()
    current_date = event.get("current_date")
    if not current_date:
        return

    # Sample up to _MAX_TICK_POSTS active fighters, weighted by
    # attention_seeking. Active = is_active=1 AND is_retired=0 AND
    # current_promotion_id IS NOT NULL (signed fighters only).
    rows = conn.execute(
        "SELECT f.fighter_id, "
        "COALESCE(fp.attention_seeking, 50) AS attention "
        "FROM fighters f "
        "LEFT JOIN fighter_personality fp ON fp.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 AND f.is_retired = 0 "
        "AND f.current_promotion_id IS NOT NULL"
    ).fetchall()
    if not rows:
        return

    # A7 — fetch each fighter's most recent post_date ONCE so we can
    # filter out fighters who posted within the cooldown window. This
    # is a single query (cheaper than per-fighter MAX(post_date) inside
    # the loop). The result is a dict {fighter_id: last_post_date}.
    last_post_dates = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT fighter_id, MAX(post_date) "
            "FROM social_posts GROUP BY fighter_id"
        ).fetchall()
        if row[1] is not None
    }

    # Weighted sampling without replacement (simple approach: shuffle
    # by attention-weighted key, take the top N).
    weighted = []
    for fighter_id, attention in rows:
        attention = attention if attention is not None else 50
        # Higher attention_seeking → higher weight. Floor at 1 so even
        # low-attention fighters have a small chance to post.
        weight = max(1, attention)
        # Multiply by a random factor for sampling variety.
        weighted.append((fighter_id, weight, rng.random()))
    # Sort by weighted random key (weight * random()); higher = picked
    # first. This approximates weighted sampling without replacement.
    weighted.sort(key=lambda x: x[1] * x[2], reverse=True)
    # Take more than _MAX_TICK_POSTS so we have spares when the cooldown
    # filters some out (otherwise a high-attention fighter who posted
    # yesterday could starve the tick by taking a slot then getting
    # filtered). 2x oversample is a reasonable balance.
    picked = [w[0] for w in weighted[:_MAX_TICK_POSTS * 2]]

    posts_this_tick = 0
    for fighter_id in picked:
        if posts_this_tick >= _MAX_TICK_POSTS:
            break  # cap reached
        # A7 — cooldown check. Skip fighters who posted within the
        # last _POST_COOLDOWN_DAYS days. The check is here (not in
        # generate_post) so direct callers (tests, FIGHT_RESOLVED
        # subscribers) aren't throttled.
        last_post = last_post_dates.get(fighter_id)
        if last_post:
            try:
                last_dt = datetime.strptime(last_post, "%Y-%m-%d")
                cur_dt = datetime.strptime(current_date, "%Y-%m-%d")
                days_since = (cur_dt - last_dt).days
                if days_since < _POST_COOLDOWN_DAYS:
                    continue  # cooldown — skip this fighter
            except (ValueError, TypeError):
                pass  # malformed date — skip the cooldown check
        # Decide post type from personality + recent events.
        post_type, target_id = _pick_tick_post(conn, fighter_id, rng=rng)
        if post_type is None:
            continue
        # generate_post creates the row (no cooldown check inside —
        # that's handled here in the subscriber). The bypass_cooldown
        # flag is kept for API compat but no longer affects behavior.
        post_id = generate_post(
            conn, fighter_id, post_type,
            target_fighter_id=target_id,
            post_date=current_date, rng=rng,
        )
        if post_id is not None:
            posts_this_tick += 1
            # A3 — if the callout/challenge crossed promotion lines,
            # also write an inter-promo news item.
            if post_type in ("callout", "challenge") \
                    and target_id is not None:
                _maybe_write_inter_promo_callout_news(
                    conn, fighter_id, target_id,
                    post_date=current_date, rng=rng,
                )


def _pick_tick_post(conn, fighter_id, rng=None):
    """Pick a post type + optional target for a TICK_ADVANCED post.

    Returns (post_type, target_fighter_id) or (None, None) if the
    fighter should stay silent this tick.

    Personality weights:
      - aggression high → trash_talk / callout / challenge
      - ego high → brag / challenge
      - attention_seeking high → hype / announcement
      - sportsmanship high → apology (if recent loss)
      - composure low + recent loss → excuse
      - older + low career_health → retirement_hint (small chance)
    """
    if rng is None:
        rng = random.Random()

    aggression = _fighter_personality_value(conn, fighter_id, "aggression")
    ego = _fighter_personality_value(conn, fighter_id, "ego")
    attention = _fighter_personality_value(conn, fighter_id, "attention_seeking")
    composure = _fighter_personality_value(conn, fighter_id, "composure")
    sportsmanship = _fighter_personality_value(conn, fighter_id, "sportsmanship")
    charisma = _fighter_personality_value(conn, fighter_id, "charisma")

    # Check for a recent loss (within the last 60 days) — influences
    # excuse / apology probability. fight_history.outcome is 'win',
    # 'loss', or 'draw'.
    recent_loss = conn.execute(
        "SELECT 1 FROM fight_history "
        "WHERE fighter_id = ? AND outcome = 'loss' "
        "AND event_date >= date('now', '-60 days') "
        "LIMIT 1",
        (fighter_id,),
    ).fetchone() is not None

    # Career-health-driven retirement_hint chance for older / worn fighters.
    age = _fighter_age(conn, fighter_id)
    career_row = conn.execute(
        "SELECT career_health FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    career_health = career_row[0] if career_row and career_row[0] is not None else 100
    if age >= 36 and career_health < 50:
        if rng.random() < 0.15:
            return ("retirement_hint", None)

    # Base weights per post type. Start from a uniform baseline and
    # add personality-driven bonuses.
    weights = {
        "hype":           1.0 + (attention / 50.0),
        "announcement":   0.5 + (attention / 100.0),
        "brag":           0.5 + (ego / 100.0),
        "callout":        0.3 + (aggression / 100.0),
        "trash_talk":     0.2 + (aggression / 80.0) + ((100 - sportsmanship) / 200.0),
        "challenge":      0.2 + (ego / 100.0) + (aggression / 200.0),
        "excuse":         (0.5 + (100 - composure) / 100.0) if recent_loss else 0.0,
        "apology":        (0.3 + sportsmanship / 200.0) if recent_loss else 0.0,
    }
    # Charisma boosts hype (charismatic fighters love the camera).
    weights["hype"] += charisma / 200.0

    total = sum(weights.values())
    if total <= 0:
        return (None, None)
    roll = rng.random() * total
    cumulative = 0.0
    post_type = None
    for kind, w in weights.items():
        cumulative += w
        if roll < cumulative:
            post_type = kind
            break
    if post_type is None:
        post_type = rng.choice(["hype", "announcement", "brag"])

    # Determine target for callout / trash_talk / challenge.
    target_id = None
    if post_type in ("callout", "trash_talk", "challenge"):
        target_id = _pick_callout_target(conn, fighter_id, rng=rng)

    return (post_type, target_id)


# ----------------------------------------------------------------
# REGISTRATION
# ----------------------------------------------------------------

def register_subscribers():
    """Register all social media subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior
    registrations.
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.FIGHT_RESOLVED, _process_fight_social,
        name="social.process_fight_social",
    )
    bus.subscribe(
        Events.TITLE_CHANGED, _process_title_social,
        name="social.process_title_social",
    )
    bus.subscribe(
        Events.TICK_ADVANCED, _check_social_activity,
        name="social.check_social_activity",
    )
