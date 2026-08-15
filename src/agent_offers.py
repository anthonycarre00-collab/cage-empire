"""CAGE EMPIRE Agent Offers / Unknown Talent Gamble System (Phase C).

This module wires the "Talent Hunter" fantasy (CAGE_EMPIRE_SOUL.md
Fantasy 1 — "I find greatness before anyone else"). An agent
periodically calls the player with a "mystery box" offer: a vague
description of a fighter (voice descriptors ONLY — NO raw attributes,
potential numbers, or career state per CONVENTIONS §14) with an
asking price. The player decides: sign the gamble, or pass. Offers
expire after 14 days.

Entirely event-bus-driven (CONVENTIONS §15.4 — no new inline side
effects added to resolve_next_fight or run_tick). Subscribes to
TICK_ADVANCED for both the offer-generation roll (weekly — 10%
chance per week, the rarity keeps each offer meaningful) and the
offer-expiry scan (every tick — cheap, just a date comparison).
resolve_offer is called directly by the UI (not a subscriber) —
the player picks Accept / Reject on a specific offer.

CONVENTIONS compliance:
  §5  — One table-group per task. The `agent_offers` table is the
        single group this task adds (along with its writer — this
        module's subscribers — and its reader — get_active_offers
        for the UI + resolve_offer which writes the resolution).
  §13 — Design Law: Discovery (the player uncovers hidden talent
        via the gamble). Anticipation (a fresh offer sits in the
        player's inbox for 14 days — will they pull the trigger?).
        Stories (the unknown talent who turns out to be a future
        champion is the storyline the player remembers forever; the
        washout veteran who flames out is the cautionary tale).
  §14 — Voice Layer: NO raw attribute values, potential numbers,
        age-as-int, record wins/losses appear in any player-facing
        description text. The fighter_description column is built
        from voice.describe_career_stage + style archetype adjective
        + voice.describe_attribute noun phrases. The asking_price
        is currency (displayed as a dollar amount in the UI — currency
        is NOT a fighter attribute, so §14 allows it). The fighter_id
        is stored for the sign path but NOT shown to the player (the
        player sees only the description until they sign).
  §15 — Event Bus: the agent offers system is entirely event-driven.
        It subscribes to TICK_ADVANCED for generation + expiry. It
        does NOT add any inline side effects to run_tick — the offer
        writes happen as a downstream subscriber.

OFFER TYPES (5 — schema CHECK constraint):
  unknown_talent       — brand-new fighter generated for the offer.
                         Description: "An unknown talent from {nation}.
                         The agent says he's got {descriptor}."
  washout_veteran      — existing free agent, a veteran past their
                         prime. Description: "A washed-up veteran
                         looking for one last run. {career_stage}.
                         Might have something left."
  style_specialist     — existing free agent whose style archetype
                         fills a gap. Description: "A style specialist
                         — {style_descriptor} who could fill a gap in
                         your roster."
  contender_release    — existing free agent recently released by
                         another promotion. Description: "{career_
                         stage_descriptor}. Was making noise in
                         another promotion — now available."
  prospect_gamble      — brand-new fighter, framed as high-risk /
                         high-reward. Description: "A raw prospect —
                         high ceiling, low floor. The agent says
                         the tools are there but the polish isn't."

OFFER FREQUENCY:
  10% chance per WEEKLY tick (current_day % 7 == 0). With ~52 weeks
  per sim year, the player sees ~5 offers per year on average. The
  rarity is intentional — the player should look forward to each
  offer, not be drowned in them. (A 50% chance per week would be 26
  offers/year — too many, the gamble loses meaning.)

OFFER EXPIRY:
  Each offer has expires_date = offer_date + 14 days. The
  _check_expired_offers subscriber fires on every TICK_ADVANCED and
  marks unresolved offers past their expires_date as is_resolved=1,
  resolution='expired'. The player never sees expired offers in the
  UI — they just disappear.

USAGE:
  from agent_offers import register_subscribers, resolve_offer,
      get_active_offers
  register_subscribers()  # call once at startup (UI App.__init__,
                          # test setup). Safe to call multiple times.
  # The agent offers system processes TICK_ADVANCED automatically
  # via the bus. The UI reads offers via get_active_offers and calls
  # resolve_offer when the player clicks Accept/Reject.

DESIGN DECISIONS:
  - The agent offers are only generated for the PLAYER's promotion
    (promotion_id=1 — Alpha Combat in the small seed, the first
    promotion in the world seed). The AI promotions get free-agent
    signings via existing paths (sign_free_agent). This keeps the
    feature scoped to the player's experience — a rival promotion
    getting agent offers would generate no player-facing narrative.
  - The offer can EITHER generate a brand-new fighter (via
    app.generate_fighter) OR pick an existing free agent. The split
    is 50/50 by default — both paths produce the same kind of
    "mystery box" experience for the player. Generated fighters
    have no record (0-0-0) and no title history, so the description
    is appropriately vague. Existing free agents have a career history
    the description can hint at (career_stage descriptor from
    voice.py).
  - The asking_price is computed from the fighter's potential (the
    only internal signal that maps to "how good could this fighter
    be"). Higher potential = higher asking price. The player never
    sees the potential number — they see the dollar figure and have
    to guess whether it's worth the gamble. The price range is
    $10k–$100k (cheap prospect → elite contender), clamped.
  - resolve_offer with accept=True deducts asking_price from the
    promotion's current_cash. If the promotion can't afford it,
    the sign is refused with a printed warning (defensive — the UI
    should also disable the Accept button when cash < asking_price,
    but the server-side check is the source of truth).
"""

import random
from datetime import datetime, timedelta


# ----------------------------------------------------------------
# Constants
# ----------------------------------------------------------------

# 10% chance per weekly tick of generating a new agent offer. The
# rarity is intentional — each offer should feel like a meaningful
# "your agent calls you" moment, not spam. With ~52 weeks/sim-year,
# the player sees ~5 offers per year on average.
OFFER_GENERATION_CHANCE = 0.10

# Offer expires after 14 days. Long enough that the player has a
# few advance-day cycles to decide; short enough that stale offers
# don't clutter the UI indefinitely.
OFFER_DURATION_DAYS = 14

# Asking price range (USD). Clamped to this range — the price scales
# with the fighter's potential (higher potential = higher price).
ASKING_PRICE_MIN = 10000.0
ASKING_PRICE_MAX = 100000.0

# The player's promotion — agent offers are only generated for the
# player, not for AI promotions. The small seed assigns Alpha Combat
# promotion_id=1; the world seed's first promotion is also id=1 by
# AUTOINCREMENT. If the player runs a non-default world, this constant
# may need adjustment (a future task could store the player's
# promotion_id in a settings table).
PLAYER_PROMOTION_ID = 1

# Probability that a generated offer uses a brand-new fighter (vs.
# an existing free agent). 50/50 split — both flavors produce the
# "mystery box" feel. The free-agent path requires at least one
# active free agent in the DB; if none exist, the generator falls
# back to the new-fighter path.
NEW_FIGHTER_PROBABILITY = 0.50


# ----------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------

def _is_weekly_tick(conn):
    """Return True if the current sim day is a multiple of 7 (weekly tick).

    Mirrors the helper used by morale.py and news.py — the sim runs
    daily ticks but we only want to roll for a new offer once per
    sim week (otherwise a 10% chance per day would generate ~37
    offers per year, drowning the player).
    """
    row = conn.execute(
        "SELECT simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    if not row or row[0] is None:
        return False
    return (row[0] % 7) == 0


def _today(conn):
    """Return the sim clock's current_date (or a sensible default)."""
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    return row[0] if row else "2026-07-20"


def _add_days(date_str, days):
    """Add `days` to an ISO date string, return ISO date string.

    Returns the original date_str if parsing fails (defensive — the
    seed DB sometimes has weird dates on historical rows).
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_str


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


def _fighter_age(conn, fighter_id, current_date=None):
    """Compute a fighter's age based on DOB and a reference date."""
    if fighter_id is None:
        return 30
    row = conn.execute(
        "SELECT date_of_birth FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row or not row[0]:
        return 30
    dob_str = row[0]
    ref_str = current_date
    if ref_str is None:
        ref_str = _today(conn)
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d")
        ref = datetime.strptime(ref_str, "%Y-%m-%d")
        age = ref.year - dob.year
        if (ref.month, ref.day) < (dob.month, dob.day):
            age -= 1
        return age
    except (ValueError, TypeError):
        return 30


def _fighter_style_archetype_name(conn, fighter_id):
    """Return the fighter's style archetype name (e.g., 'Striker').

    Returns 'Balanced' as a defensive fallback.
    """
    if fighter_id is None:
        return "Balanced"
    row = conn.execute(
        "SELECT sa.name FROM fighters f "
        "LEFT JOIN style_archetypes sa "
        "  ON sa.style_archetype_id = f.fight_style_archetype_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] else "Balanced"


def _fighter_birth_nation_name(conn, fighter_id):
    """Return the fighter's birth nation name (or 'parts unknown')."""
    if fighter_id is None:
        return "parts unknown"
    row = conn.execute(
        "SELECT n.name FROM fighters f "
        "LEFT JOIN nations n ON n.nation_id = f.birth_nation_id "
        "WHERE f.fighter_id=?",
        (fighter_id,),
    ).fetchone()
    return row[0] if row and row[0] else "parts unknown"


def _fighter_career_stage(conn, fighter_id, rng=None, current_date=None):
    """Return the fighter's career stage descriptor (voice layer).

    Uses voice.describe_career_stage with the fighter's observable
    state (age, record, champion status, streaks). Does NOT reveal
    hidden potential. Falls back to a generic phrase if voice.py
    is unavailable (defensive — headless test paths).
    """
    if fighter_id is None:
        return "roster fighter"
    try:
        from voice import describe_career_stage
    except ImportError:
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


def _fighter_top_attribute_phrase(conn, fighter_id, rng=None):
    """Return a noun-phrase descriptor for the fighter's TOP attribute.

    Uses voice.describe_attribute on the fighter's highest-value
    attribute. Falls back to "a serviceable skill set" if attributes
    are missing. The phrase is grammatical as a noun (e.g., "elite
    power", "strong cardio") so it fits the description template
    slots ("the agent says he's got {descriptor}").
    """
    if fighter_id is None:
        return "a serviceable skill set"
    try:
        from voice import describe_attribute
    except ImportError:
        return "a serviceable skill set"
    attr_names = [
        "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
        "head_movement", "footwork", "clinch_striking", "clinch_offense",
        "clinch_defense", "takedown_offense", "takedown_defense",
        "top_control", "bottom_game", "submission_offense",
        "submission_defense", "scramble_ability", "cage_wrestling",
        "cardio", "recovery_rate", "speed_explosiveness", "strength",
        "durability", "flexibility", "fight_iq", "chin", "adaptability",
    ]
    cols_sql = ", ".join(attr_names)
    row = conn.execute(
        f"SELECT {cols_sql} FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "a serviceable skill set"
    paired = list(zip(attr_names, row))
    paired.sort(key=lambda x: (x[1] if x[1] is not None else 0), reverse=True)
    attr_name, value = paired[0]
    if value is None:
        return "a serviceable skill set"
    desc = describe_attribute(attr_name, value, rng=rng)
    return desc or "a serviceable skill set"


def _style_specialist_phrase(style_archetype_name, rng=None):
    """Return a short noun phrase for a style specialist offer.

    Maps style archetype names to evocative phrases the agent would
    use: "a polished striker", "a slick grappler", "a relentless
    wrestler", etc. Word-form only — NO digit characters (§14).
    """
    if rng is None:
        rng = random
    phrases = {
        "Striker": ["a polished striker", "a heavy-handed kickboxer",
                    "a sharp boxer-puncher"],
        "Grappler": ["a slick grappler", "a submission-hunter",
                     "a smooth ground specialist"],
        "Wrestler": ["a relentless wrestler", "a grinding cage wrestler",
                     "a takedown machine"],
        "Brawler": ["a wild brawler", "a heavy-handed swinger",
                    "a fight-anywhere bruiser"],
        "Counter-Striker": ["a patient counter-striker",
                            "a wait-and-pounce counter-puncher",
                            "a sharp counter fighter"],
        "Submission Specialist": ["a slick submission specialist",
                                  "a tap-hunter",
                                  "a crafty submission player"],
        "Balanced": ["a well-rounded talent", "a do-everything fighter",
                     "a versatile prospect"],
    }
    return rng.choice(phrases.get(style_archetype_name,
                                  phrases["Balanced"]))


def _pick_offer_type(rng):
    """Pick an offer_type for a new agent offer.

    Weighted toward unknown_talent + prospect_gamble (the most
    evocative flavors — a true mystery box). The other types
    (washout_veteran, style_specialist, contender_release) are
    less common — they require an existing free agent and the
    narrative is more specific.
    """
    # Weights: unknown_talent 30%, prospect_gamble 25%, washout 15%,
    # style_specialist 15%, contender_release 15%.
    return rng.choices(
        ['unknown_talent', 'prospect_gamble', 'washout_veteran',
         'style_specialist', 'contender_release'],
        weights=[30, 25, 15, 15, 15],
    )[0]


def _compute_asking_price(conn, fighter_id):
    """Compute the asking price for a fighter offer.

    Scales with potential (the only internal signal that maps to
    "how good could this fighter be"). Higher potential = higher
    asking price. The player never sees the potential number —
    they see the dollar figure and have to guess whether it's worth
    the gamble. The price range is $10k–$100k, clamped.

    The formula is deliberately non-linear so elite potential (75+)
    commands a meaningful premium — a potential-90 fighter should
    feel expensive, not just slightly pricier than a potential-50.

    PHASE M3.3 (docs/MASTER_PLAN_MATCHMAKING.md §2.2): the asking
    price now uses `effective_ceiling = potential * realization`
    instead of raw potential. A "bust" (potential=85, realization=0.5,
    effective_ceiling=42) is priced like a 42-potential fighter — not
    the same as a "realizer" (potential=85, realization=1.0, ceiling=85).
    The rival AI's fair-value formula (signing_agent._fair_value) was
    also updated to use effective_ceiling, so neither side overpays
    for busts.
    """
    if fighter_id is None:
        return ASKING_PRICE_MIN
    row = conn.execute(
        "SELECT potential, realization FROM fighter_career WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    potential = row[0] if row and row[0] is not None else 50
    realization = row[1] if row and row[1] is not None else 0.7
    # M3.3: effective_ceiling = potential * realization.
    effective_ceiling = potential * realization
    # Linear 10k–100k mapping: effective_ceiling 0 → $10k, 100 → $100k.
    # A bust (potential=85, realization=0.5, ceiling=42) costs ~$46k;
    # a realizer (potential=85, realization=1.0, ceiling=85) costs ~$86k.
    price = ASKING_PRICE_MIN + (effective_ceiling / 100.0) * (
        ASKING_PRICE_MAX - ASKING_PRICE_MIN
    )
    # Add ±10% noise so two effective_ceiling=72 fighters don't have
    # identical prices (the agent's asking price has some wiggle room).
    noise = 1.0 + random.uniform(-0.10, 0.10)
    price = price * noise
    return round(max(ASKING_PRICE_MIN, min(ASKING_PRICE_MAX, price)), 2)


def _build_description(conn, fighter_id, offer_type, rng=None):
    """Build the voice-layer-driven fighter_description.

    The description is the "mystery box" text the player sees in the
    UI. It uses voice descriptors (career_stage + style adjective +
    top attribute phrase) — NEVER raw attributes, potential, age-as-
    int, or record wins/losses per CONVENTIONS §14.

    Each offer_type has its own template + variants for variety.
    """
    if rng is None:
        rng = random
    if fighter_id is None:
        return "An agent has a fighter they want to shop around."

    nation = _fighter_birth_nation_name(conn, fighter_id)
    style_name = _fighter_style_archetype_name(conn, fighter_id)
    career_stage = _fighter_career_stage(conn, fighter_id, rng=rng)
    top_attr = _fighter_top_attribute_phrase(conn, fighter_id, rng=rng)
    style_phrase = _style_specialist_phrase(style_name, rng=rng)

    if offer_type == 'unknown_talent':
        # Brand-new fighter; nation + style + a single attribute phrase.
        templates = [
            f"An unknown talent from {nation}. The agent says he's got "
            f"{top_attr}. Asking price steep — but you'd be the first "
            f"to find out if it's worth it.",
            f"Fresh face from {nation}. Word is he brings {top_attr}. "
            f"No tape on the kid — you'd be betting on the agent's eye.",
            f"A complete unknown out of {nation}. The pitch: {top_attr}. "
            f"The agent swears there's something there. Might be.",
        ]
    elif offer_type == 'washout_veteran':
        # Existing free agent, a veteran. career_stage descriptor hints
        # at the stage ("grizzled veteran", "former contender") without
        # revealing the exact age or record.
        templates = [
            f"A washed-up veteran looking for one last run. Currently a "
            f"{career_stage} — might have something left in the tank, "
            f"might be chasing a paycheck. The agent says {top_attr} "
            f"is still there.",
            f"Veteran fighter, {career_stage}, available on the cheap. "
            f"The miles are on him but the {top_attr} hasn't gone "
            f"anywhere. Could be a steal. Could be a farewell tour.",
            f"An older hand looking for a landing spot — a {career_stage} "
            f"who's been around. The agent pitches {top_attr} as the "
            f"reason to take the chance.",
        ]
    elif offer_type == 'style_specialist':
        # Existing free agent whose style fills a gap.
        templates = [
            f"A style specialist — {style_phrase} who could fill a gap "
            f"in your roster. The agent says the {top_attr} is real. "
            f"Worth a look if the division needs that look.",
            f"Free agent available: {style_phrase} with {top_attr}. "
            f"Could be exactly the piece your card is missing — or "
            f"could be a square peg in a round hole.",
            f"Specialist on the market — {style_phrase}. The agent is "
            f"selling {top_attr} as the headline trait. You'd know "
            f"after one fight if it translates.",
        ]
    elif offer_type == 'contender_release':
        # Existing free agent recently released by another promotion.
        templates = [
            f"A {career_stage} who just became available — released by "
            f"another promotion. The agent says the {top_attr} is "
            f"legit; the other promotion just didn't have the spot. "
            f"Could be your gain.",
            f"Just-released free agent, {career_stage}, hits the open "
            f"market. The {top_attr} is what the agent is selling. "
            f"Someone's castoff, someone else's contender.",
            f"Recently released — a {career_stage} looking for a fresh "
            f"start. The pitch: {top_attr}, plus a chip on the "
            f"shoulder. The agent says he'll fight like he's got "
            f"something to prove. Probably does.",
        ]
    else:  # prospect_gamble
        # Brand-new fighter, framed as high-risk / high-reward.
        templates = [
            f"A raw prospect from {nation} — high ceiling, low floor. "
            f"The agent says the {top_attr} is real, but the polish "
            f"isn't. You'd be betting on the come-up.",
            f"Baby-faced kid out of {nation}. The tools — {top_attr} "
            f"— are there, but the reps aren't. Could be a future "
            f"champion. Could be out of the sport in two years.",
            f"Project prospect from {nation}. The agent pitches "
            f"{top_attr} as the seed of something bigger. The raw "
            f"materials are real. Whether they become anything is "
            f"the gamble.",
        ]
    return rng.choice(templates)


# ----------------------------------------------------------------
# Writer — TICK_ADVANCED subscriber
# ----------------------------------------------------------------

def _maybe_generate_offer(conn, event):
    """TICK_ADVANCED subscriber — roll for a new agent offer weekly.

    Per the brief: 10% chance per WEEKLY tick of generating an agent
    offer for the player's promotion. The offer is a "mystery box"
    — the player sees a vague description (voice descriptors only,
    NO raw attributes per §14) and an asking price. The offer
    expires after OFFER_DURATION_DAYS (14) days.

    The fighter can be EITHER:
      1. A brand-new fighter generated via app.generate_fighter
         (the agent found someone off the radar), OR
      2. An existing free agent (current_promotion_id IS NULL,
         is_active=1, is_retired=0).

    The split is 50/50 by default (NEW_FIGHTER_PROBABILITY). If no
    free agents exist, the generator falls back to the new-fighter
    path. If the new-fighter path fails (name pool exhausted —
    defensive), the offer is silently skipped.

    Defensive — early-returns if:
      - The tick is not weekly (we only roll on weekly ticks).
      - The player's promotion doesn't exist.
      - The roll fails (90% of weekly ticks).
      - There's already an unresolved offer for the player's
        promotion (max 1 pending offer at a time — keeps the UI
        focused, prevents offer spam).

    For testing, the OFFER_GENERATION_CHANCE constant can be
    monkey-patched to 1.0 to force generation on every weekly tick.
    """
    # Only roll on weekly ticks — otherwise a 10% chance per day
    # would generate ~37 offers per year, drowning the player.
    if not _is_weekly_tick(conn):
        return

    rng = random.Random()

    # 10% chance per weekly tick.
    if rng.random() >= OFFER_GENERATION_CHANCE:
        return

    # Verify the player's promotion exists.
    promo_row = conn.execute(
        "SELECT 1 FROM promotions WHERE promotion_id=?",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()
    if not promo_row:
        return

    # Max 1 pending offer at a time — keeps the UI focused.
    existing_pending = conn.execute(
        "SELECT 1 FROM agent_offers "
        "WHERE promotion_id=? AND is_resolved=0",
        (PLAYER_PROMOTION_ID,),
    ).fetchone()
    if existing_pending:
        return

    # Pick the offer_type + fighter.
    offer_type = _pick_offer_type(rng)
    fighter_id = None

    # 50/50 split: new fighter vs. existing free agent.
    use_new_fighter = rng.random() < NEW_FIGHTER_PROBABILITY
    # Some offer types REQUIRE a new fighter (no history); others
    # require an existing free agent. Adjust the split per type:
    if offer_type in ('unknown_talent', 'prospect_gamble'):
        # These are brand-new fighters by definition.
        use_new_fighter = True
    elif offer_type in ('washout_veteran', 'contender_release',
                        'style_specialist'):
        # These require an existing free agent (career history).
        use_new_fighter = False

    if not use_new_fighter:
        # Pick an existing free agent — active, not retired, no
        # current promotion. Exclude fighters who already have a
        # pending offer (max 1 offer per fighter at a time).
        rows = conn.execute(
            "SELECT f.fighter_id FROM fighters f "
            "WHERE f.is_active=1 AND f.is_retired=0 "
            "AND f.current_promotion_id IS NULL "
            "AND f.fighter_id NOT IN ("
            "    SELECT fighter_id FROM agent_offers "
            "    WHERE is_resolved=0)"
        ).fetchall()
        if rows:
            fighter_id = rng.choice(rows)[0]
        else:
            # No free agents available — fall back to generating a
            # new fighter (the offer becomes an 'unknown_talent' /
            # 'prospect_gamble' flavored gamble on a new face).
            use_new_fighter = True
            # Re-classify the offer type so the description matches
            # the actual fighter (a new fighter can't be a
            # 'washout_veteran' or 'contender_release').
            offer_type = rng.choice(['unknown_talent', 'prospect_gamble'])

    if use_new_fighter:
        # Generate a brand-new fighter via app.generate_fighter.
        # Lazy-import to avoid circular dependency at module load.
        try:
            from app import generate_fighter
        except ImportError:
            return  # app.py not available (headless test path)
        current_date = event.get('current_date') or _today(conn)
        fighter_id = generate_fighter(
            conn, style_dna_source_id=None,
            current_date=current_date,
            gender=rng.choice(['male', 'female']),
        )
        if fighter_id is None:
            return  # name pool exhausted (defensive — shouldn't happen)

    # Build the voice-layer-driven description.
    description = _build_description(
        conn, fighter_id, offer_type, rng=rng,
    )

    # Compute asking price from the fighter's potential.
    asking_price = _compute_asking_price(conn, fighter_id)

    # Compute offer_date + expires_date.
    offer_date = event.get('current_date') or _today(conn)
    expires_date = _add_days(offer_date, OFFER_DURATION_DAYS)

    # Insert the offer row.
    conn.execute(
        "INSERT INTO agent_offers "
        "(promotion_id, fighter_id, offer_date, offer_type, "
        " asking_price, fighter_description, is_resolved, "
        " resolution, resolution_date, expires_date) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?)",
        (PLAYER_PROMOTION_ID, fighter_id, offer_date, offer_type,
         asking_price, description, expires_date),
    )


def _check_expired_offers(conn, event):
    """TICK_ADVANCED subscriber — expire offers past their expires_date.

    Scans `agent_offers` for unresolved rows where expires_date <
    current_date. For each, sets is_resolved=1, resolution='expired',
    resolution_date=current_date. The fighter remains a free agent
    (no current_promotion_id change) — they just disappear from the
    player's offer inbox.

    Defensive — early-returns if event has no current_date.
    """
    current_date = event.get('current_date')
    if not current_date:
        return

    expired = conn.execute(
        "SELECT offer_id FROM agent_offers "
        "WHERE is_resolved=0 AND expires_date < ?",
        (current_date,),
    ).fetchall()
    for (offer_id,) in expired:
        conn.execute(
            "UPDATE agent_offers SET is_resolved=1, "
            "resolution='expired', resolution_date=? "
            "WHERE offer_id=?",
            (current_date, offer_id),
        )


# ----------------------------------------------------------------
# Reader + resolver — called directly by the UI
# ----------------------------------------------------------------

def get_active_offers(conn, promotion_id=None):
    """Return all pending (unresolved) agent offers for a promotion.

    Args:
        conn: sqlite3.Connection (read-only — caller does not commit).
        promotion_id: the promotion to filter on. Defaults to the
            player's promotion (PLAYER_PROMOTION_ID).

    Returns:
        A list of offer rows (as tuples — same shape as
        `SELECT * FROM agent_offers`), ordered by offer_date DESC
        (newest first). Empty list if no pending offers.
    """
    if promotion_id is None:
        promotion_id = PLAYER_PROMOTION_ID
    return conn.execute(
        "SELECT * FROM agent_offers "
        "WHERE promotion_id=? AND is_resolved=0 "
        "ORDER BY offer_date DESC",
        (promotion_id,),
    ).fetchall()


def resolve_offer(conn, offer_id, accept=True, current_date=None):
    """Resolve an agent offer — sign the fighter or reject the offer.

    Called directly by the UI when the player clicks Accept / Reject
    on a specific offer. NOT an event-bus subscriber — the player's
    decision is a direct action, not a game-tick event.

    Args:
        conn: sqlite3.Connection (caller commits).
        offer_id: the agent_offers.offer_id to resolve.
        accept: True → sign the fighter (sets current_promotion_id,
            deducts asking_price from the promotion's current_cash).
            False → mark the offer as rejected (fighter remains a
            free agent).
        current_date: ISO date string for the resolution_date. If
            None, uses the sim clock's current_date.

    Returns:
        True on success, False on failure (offer not found, already
        resolved, promotion can't afford the asking price, etc.).
    """
    if current_date is None:
        current_date = _today(conn)

    row = conn.execute(
        "SELECT promotion_id, fighter_id, asking_price, is_resolved "
        "FROM agent_offers WHERE offer_id=?",
        (offer_id,),
    ).fetchone()
    if not row:
        print(f"Warning: agent offer {offer_id} not found.")
        return False
    promotion_id, fighter_id, asking_price, is_resolved = row
    if is_resolved:
        print(f"Warning: agent offer {offer_id} is already resolved.")
        return False

    if accept:
        # Verify the fighter is still a free agent (defensive — could
        # have been signed by another path between offer + resolution).
        fa_row = conn.execute(
            "SELECT current_promotion_id, is_active, is_retired "
            "FROM fighters WHERE fighter_id=?",
            (fighter_id,),
        ).fetchone()
        if not fa_row:
            print(f"Warning: fighter {fighter_id} not found — "
                  f"cannot sign.")
            return False
        cur_promo, is_active, is_retired = fa_row
        if cur_promo is not None:
            print(f"Warning: fighter {fighter_id} is already signed "
                  f"to promotion {cur_promo} — cannot accept offer.")
            # Mark the offer as rejected (the fighter is no longer
            # available; the player's "accept" is moot).
            conn.execute(
                "UPDATE agent_offers SET is_resolved=1, "
                "resolution='rejected', resolution_date=? "
                "WHERE offer_id=?",
                (current_date, offer_id),
            )
            return False
        if is_retired or not is_active:
            print(f"Warning: fighter {fighter_id} is retired or "
                  f"inactive — cannot sign.")
            conn.execute(
                "UPDATE agent_offers SET is_resolved=1, "
                "resolution='rejected', resolution_date=? "
                "WHERE offer_id=?",
                (current_date, offer_id),
            )
            return False

        # Verify the promotion can afford the asking price.
        cash_row = conn.execute(
            "SELECT current_cash FROM promotions WHERE promotion_id=?",
            (promotion_id,),
        ).fetchone()
        current_cash = cash_row[0] if cash_row else 0.0
        if current_cash < asking_price:
            print(f"Warning: promotion {promotion_id} cannot afford "
                  f"asking price {asking_price} (cash={current_cash}). "
                  f"Offer rejected.")
            conn.execute(
                "UPDATE agent_offers SET is_resolved=1, "
                "resolution='rejected', resolution_date=? "
                "WHERE offer_id=?",
                (current_date, offer_id),
            )
            return False

        # Sign the fighter: set current_promotion_id + deduct
        # asking_price from the promotion's current_cash. We do NOT
        # use sign_free_agent here because sign_free_agent creates a
        # contracts row with a default salary — agent offer signings
        # use the asking_price as the signing bonus (not a salary).
        # The contracts row can be added later by a follow-up task;
        # for now, the fighter is on the roster (current_promotion_id
        # set) and the cash is deducted. The news engine's
        # FIGHTER_SIGNED event is published by the bus if the UI
        # chooses to fire it (this function does NOT publish — the
        # bus publish is the caller's responsibility, kept here as
        # a direct DB write to keep the resolver simple).
        conn.execute(
            "UPDATE fighters SET current_promotion_id=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (promotion_id, fighter_id),
        )
        conn.execute(
            "UPDATE promotions SET current_cash=current_cash-?, "
            "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
            (asking_price, promotion_id),
        )
        conn.execute(
            "UPDATE agent_offers SET is_resolved=1, "
            "resolution='signed', resolution_date=? "
            "WHERE offer_id=?",
            (current_date, offer_id),
        )
        return True
    else:
        # Reject — mark the offer as rejected. The fighter remains
        # a free agent (no current_promotion_id change).
        conn.execute(
            "UPDATE agent_offers SET is_resolved=1, "
            "resolution='rejected', resolution_date=? "
            "WHERE offer_id=?",
            (current_date, offer_id),
        )
        return True


# ----------------------------------------------------------------
# Registration
# ----------------------------------------------------------------

def register_subscribers():
    """Register all agent offers subscribers on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior registrations.

    Subscribes to:
      TICK_ADVANCED → _maybe_generate_offer (weekly roll, 10% chance)
      TICK_ADVANCED → _check_expired_offers (every tick, cheap scan)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.TICK_ADVANCED, _maybe_generate_offer,
        name="agent_offers.maybe_generate_offer",
    )
    bus.subscribe(
        Events.TICK_ADVANCED, _check_expired_offers,
        name="agent_offers.check_expired_offers",
    )
