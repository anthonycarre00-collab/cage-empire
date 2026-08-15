"""CAGE EMPIRE Hall of Fame induction service (Phase 1 — Fix 1.4).

Subscribes to FIGHTER_RETIRED. When a fighter retires, evaluates
them against HoF eligibility criteria. If eligible, inducts them
into `hall_of_fame` with a generated `career_summary` +
`career_highlights`, and writes an induction news item
(topic='hall_of_fame').

This is the Historian fantasy's foundation (CAGE_EMPIRE_SOUL.md
Fantasy 4 — "The world remembers what I built"). Without this,
every champion the player develops is forgotten on retirement —
after 50 sim years of developing champions, none of the player's
fighters would be in the HoF. The 60 seeded legends would be the
only inductees forever.

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        `hall_of_fame` already exists (built in v1.2.0, seeded with
        60 retired legends by scripts/seed_world_phase5.py). This
        module is the FIRST writer that inducts fighters who retire
        DURING gameplay.
  §13 — Design Law: Legacy pillar — HoF induction is how the world
        remembers what the player built. Strengthens the Historian
        fantasy ("The world remembers what I built").
  §14 — Voice Layer: career_summary uses voice.describe_overall
        (which internally calls voice.describe_career_stage +
        voice.describe_attribute) — NO raw attribute values, NO raw
        age, NO raw streak counts. Career stats (wins/losses/reigns)
        are OK in career_highlights — those are career stats, not
        attribute values, per the brief's clarification.
  §15 — Event Bus: subscribes to FIGHTER_RETIRED (published by
        tick_processor._check_retirements). The subscriber is
        defensive (catches exceptions, doesn't crash the bus). No
        new inline side effects are added to _check_retirements
        (§15.4 — additive only).

ELIGIBILITY (Phase 1 audit recommendation):
  A retired fighter is eligible for HoF induction if ANY of:
    - title_reigns >= 2           (multi-time champion)
    - record_wins  >= 30          (longevity + success)
    - record_wins  >= 20 AND
      title_reigns >= 1           (champion + longevity)

  These thresholds are intentionally inclusive — the Historian
  fantasy collapses if the player develops a champion for 5 sim
  years and the fighter is forgotten on retirement. The thresholds
  catch every meaningful career: multi-time champs, longevity
  winners, and champions with reasonable win totals. Fighters with
  short careers, no titles, and few wins are silently skipped (the
  world doesn't induct 8-12 journeymen).

ARCHITECTURE:
  This module follows the punditry.py pattern (an event-bus-
  subscribing service module):
    - Module-level docstring + CONVENTIONS compliance section
    - Helper functions (eligibility check, summary/highlights
      generation, news write)
    - `induce_fighter_into_hof(conn, event)` — the subscriber fn
    - `register_subscribers()` — registers the subscriber on the bus

  The subscriber is idempotent — already-inducted fighters are
  silently skipped (defensive against duplicate FIGHTER_RETIRED
  events or accidental re-publishing).

USAGE:
  from services.hof_svc import register_subscribers
  register_subscribers()  # call once at startup (UI App.__init__)

  # The system automatically processes FIGHTER_RETIRED via the bus.
  # When tick_processor._check_retirements retires a fighter and
  # publishes FIGHTER_RETIRED, this module evaluates them and
  # inducts if eligible.
"""

import random
import sys


# ----------------------------------------------------------------
# Eligibility check
# ----------------------------------------------------------------

def _is_eligible_for_hof(conn, fighter_id):
    """Check if a retired fighter meets HoF eligibility criteria.

    Criteria (ANY of):
      - title_reigns >= 2           (multi-time champion)
      - record_wins  >= 30          (longevity + success)
      - record_wins  >= 20 AND
        title_reigns >= 1           (champion + longevity)

    Args:
        conn: sqlite3 connection.
        fighter_id: the retiring fighter's ID.

    Returns:
        True if eligible, False otherwise. Returns False if the
        fighter has no fighter_career row (defensive — shouldn't
        happen with the seed, but a future mod tool could produce
        a fighter without one).
    """
    row = conn.execute(
        "SELECT fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.title_reigns "
        "FROM fighter_career fc WHERE fc.fighter_id = ?",
        (fighter_id,)
    ).fetchone()
    if not row:
        return False
    wins, losses, draws, title_reigns = row
    wins = wins or 0
    title_reigns = title_reigns or 0

    if title_reigns >= 2:
        return True
    if wins >= 30:
        return True
    if wins >= 20 and title_reigns >= 1:
        return True
    return False


# ----------------------------------------------------------------
# Career summary — voice-layered, digit-free (CONVENTIONS §14)
# ----------------------------------------------------------------

# All 25 attribute names — matches the column order in
# fighter_attributes (see build_db.py). Used to pick the fighter's
# top 2 attributes by value for the describe_overall key_attributes
# slot. Mirrors the same constant in news.py / punditry.py.
_ATTR_NAMES = [
    "punch_power", "punch_accuracy", "kick_power", "kick_accuracy",
    "head_movement", "footwork", "clinch_striking", "clinch_offense",
    "clinch_defense", "takedown_offense", "takedown_defense",
    "top_control", "bottom_game", "submission_offense",
    "submission_defense", "scramble_ability", "cage_wrestling",
    "cardio", "recovery_rate", "speed_explosiveness", "strength",
    "durability", "flexibility", "fight_iq", "chin", "adaptability",
]


def _fighter_age(conn, fighter_id, current_date=None):
    """Compute a fighter's age based on DOB and a reference date.

    Mirrors news._fighter_age. If current_date is None, falls back
    to the simulation_clock's current_date.
    """
    from datetime import datetime
    row = conn.execute(
        "SELECT date_of_birth FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not row or not row[0]:
        return 35  # defensive default — typical retirement age
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
        return 35


def _generate_career_summary(conn, fighter_id, rng=None):
    """Generate a voice-layered career summary for the HoF inductee.

    Uses voice.describe_overall (which internally calls
    voice.describe_career_stage + voice.describe_attribute) to
    produce a 1-2 sentence summary. NO raw numbers (CONVENTIONS §14)
    — no raw age, no raw attribute values, no raw streak counts.

    Example output:
        "John Vale 'Hammer' is a striker, with fight-ending power in
        both hands and excellent chin, currently grizzled veteran."

    Args:
        conn: sqlite3 connection.
        fighter_id: the inductee's fighter_id.
        rng: optional random.Random for variant selection.

    Returns:
        A 1-2 sentence summary string. Returns a generic fallback
        ("A career worth remembering — inducted into the Hall of
        Fame.") if voice.describe_overall is unavailable or the
        fighter has no attribute/career rows.
    """
    if rng is None:
        rng = random.Random()
    try:
        from voice import describe_overall
    except ImportError:
        return "A career worth remembering — inducted into the Hall of Fame."

    # Load fighter + career + style archetype. Mirrors news.
    # _fighter_overall's data load.
    row = conn.execute(
        "SELECT f.first_name, f.last_name, f.nickname, "
        "f.fight_style_archetype_id, sa.name AS style_archetype_name, "
        "fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.title_reigns, "
        "fc.career_health "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "LEFT JOIN style_archetypes sa "
        "       ON sa.style_archetype_id = f.fight_style_archetype_id "
        "WHERE f.fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    if not row:
        return "A career worth remembering — inducted into the Hall of Fame."
    (first, last, nick, sa_id, sa_name,
     wins, losses, draws, ws, ls, reigns, health) = row

    # The fighter is retired — is_champion=False (any title they held
    # was vacated by tick_processor._vacate_title_on_retirement
    # before FIGHTER_RETIRED was published). The title_reigns count
    # still captures their historical champion status, which
    # describe_career_stage uses to produce "multi-time champ" /
    # "former contender" descriptors.
    age = _fighter_age(conn, fighter_id)

    # Pull the fighter's top 2 attributes by value for the
    # key_attributes slot (mirrors news._fighter_overall). Defensive
    # — a fighter without attributes (regen replacement mid-build,
    # backfill not yet run, etc.) gets an empty key_attrs dict and
    # describe_overall skips the "with X and Y" clause.
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
        "is_champion": False,  # retired — title vacated
        "title_reigns": reigns or 0,
        "win_streak": ws or 0,
        "loss_streak": ls or 0,
        "career_health": health or 100,
        "style_archetype_name": sa_name or "Balanced",
        "key_attributes": key_attrs,
    }
    try:
        summary = describe_overall(fighter_data, rng=rng)
        if summary:
            return summary
    except Exception as e:
        # Defensive — voice.describe_overall should never raise, but
        # if it does, fall back to the generic summary rather than
        # crashing the induction.
        print(f"WARNING: hof_svc._generate_career_summary: "
              f"describe_overall raised {type(e).__name__}: {e}",
              file=sys.stderr)
    return "A career worth remembering — inducted into the Hall of Fame."


# ----------------------------------------------------------------
# Career highlights — bullet list (career stats OK per §14)
# ----------------------------------------------------------------

def _generate_career_highlights(conn, fighter_id):
    """Generate a bullet-list of career highlights for the inductee.

    Includes:
      - Title reigns (e.g., "• 3-time champion")
      - Title defenses (approximated via fight_history
        title_at_stake=1 wins minus reigns; falls back to
        fighter_career.title_reigns as a proxy per the brief)
      - Notable record (e.g., "• 28-5 career record")
      - Career stage descriptor (e.g., "• Retired as a grizzled
        veteran" — uses voice.describe_career_stage)

    Career stats (wins/losses/reigns/defenses) are OK in
    career_highlights per the brief's clarification — they're career
    stats, not attribute values. Only career_summary must be
    digit-free (CONVENTIONS §14).

    Args:
        conn: sqlite3 connection.
        fighter_id: the inductee's fighter_id.

    Returns:
        A multi-line string with bullet points (•). Returns
        "• Career highlights unavailable" if the fighter has no
        fighter_career row.
    """
    row = conn.execute(
        "SELECT fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.title_reigns, fc.win_streak, fc.loss_streak, "
        "fc.career_health "
        "FROM fighter_career fc WHERE fc.fighter_id = ?",
        (fighter_id,)
    ).fetchone()
    if not row:
        return "• Career highlights unavailable"
    wins, losses, draws, reigns, ws, ls, health = row
    wins = wins or 0
    losses = losses or 0
    draws = draws or 0
    reigns = reigns or 0
    ws = ws or 0
    ls = ls or 0
    health = health or 100

    highlights = []

    # ---- Title reigns ----
    # "3-time champion" is a career stat (number of reigns), not an
    # attribute value — OK per §14.
    if reigns >= 1:
        if reigns == 1:
            highlights.append(f"• {reigns}-time champion")
        else:
            highlights.append(f"• {reigns}-time champion")

    # ---- Title defenses ----
    # fight_history tracks every fight with title_at_stake=1. A
    # champion's defenses = title fights won minus the number of
    # times they BECAME champion (each reign starts with one
    # title-at-stake win — the vacant-title claim or the dethroning
    # of the previous champ). The remainder is defenses.
    # Defensive: if fight_history has no rows for this fighter (e.g.
    # the test DB has only the seeded fight), defenses=0 and we
    # skip the line.
    try:
        title_bouts_won = conn.execute(
            "SELECT COUNT(*) FROM fight_history "
            "WHERE fighter_id=? AND title_at_stake=1 "
            "AND outcome='win'",
            (fighter_id,)
        ).fetchone()[0]
    except Exception:
        title_bouts_won = 0
    if title_bouts_won > 0 and reigns > 0:
        defenses = max(0, title_bouts_won - reigns)
        if defenses > 0:
            highlights.append(
                f"• Defended the belt {defenses} "
                f"{'time' if defenses == 1 else 'times'}"
            )
    if title_bouts_won > 0 and reigns == 0:
        # Won a title fight but doesn't have a reign recorded —
        # defensive edge case (shouldn't happen with the seed, but
        # a future mod could create this). Just note the title bouts.
        highlights.append(
            f"• Won {title_bouts_won} championship "
            f"{'bout' if title_bouts_won == 1 else 'bouts'}"
        )

    # ---- Career record ----
    # "28-5 career record" — career stats are OK per the brief's
    # clarification (not attribute values).
    if draws > 0:
        highlights.append(f"• {wins}-{losses}-{draws} career record")
    else:
        highlights.append(f"• {wins}-{losses} career record")

    # ---- Notable streak (if any) ----
    # Career stats — OK per §14.
    if ws >= 5:
        highlights.append(f"• {ws}-fight win streak (career best)")
    elif ls >= 5:
        # A long loss streak is also a story — the fighter who
        # soldiered through tough times before retiring.
        highlights.append(f"• Endured a {ls}-fight skid late in career")

    # ---- Career stage descriptor ----
    # Uses voice.describe_career_stage (no raw numbers). Example:
    # "Retired as a grizzled veteran" / "Retired as a battle-tested
    # veteran" / "Retired as a wily veteran".
    try:
        from voice import describe_career_stage
        age = _fighter_age(conn, fighter_id)
        stage = describe_career_stage(
            age, wins, losses, draws,
            is_champion=False,
            title_reigns=reigns,
            win_streak=ws, loss_streak=ls,
        )
        highlights.append(f"• Retired as {stage}")
    except ImportError:
        # voice.py not available — skip the stage descriptor line.
        pass

    return "\n".join(highlights)


# ----------------------------------------------------------------
# Subscriber — induces qualifying fighters into the HoF
# ----------------------------------------------------------------

def induce_fighter_into_hof(conn, event):
    """Subscriber for FIGHTER_RETIRED — induce qualifying fighters
    into the Hall of Fame.

    Args:
        conn: sqlite3.Connection (caller commits).
        event: dict with at least:
            - 'type': Events.FIGHTER_RETIRED
            - 'fighter_id': the retiring fighter's ID
            - 'current_date' (optional): the sim date of retirement
              (used as inducted_date; falls back to
              simulation_clock.current_date)
            - 'event_date' (optional): alias for current_date
    """
    try:
        fighter_id = event.get("fighter_id")
        if not fighter_id:
            return

        # ---- Idempotency: already-inducted fighters are skipped ----
        # Defensive against duplicate FIGHTER_RETIRED events or
        # accidental re-publishing. The hall_of_fame table has a
        # UNIQUE constraint on fighter_id (per build_db.py), so a
        # duplicate INSERT would fail anyway — this check makes the
        # skip explicit and avoids the exception path.
        existing = conn.execute(
            "SELECT 1 FROM hall_of_fame WHERE fighter_id = ?",
            (fighter_id,)
        ).fetchone()
        if existing:
            return  # already inducted — silent skip

        # ---- Eligibility ----
        if not _is_eligible_for_hof(conn, fighter_id):
            return  # not eligible — silent skip

        # ---- Generate summary + highlights (voice-layer-driven) ----
        rng = random.Random()
        career_summary = _generate_career_summary(conn, fighter_id, rng=rng)
        career_highlights = _generate_career_highlights(conn, fighter_id)

        # ---- Determine induction date ----
        # Prefer the event's current_date / event_date (the sim date
        # the retirement happened on — published by
        # tick_processor._check_retirements). Fall back to the
        # simulation_clock's current_date. Final fallback: today's
        # ISO date (defensive — shouldn't happen, but a future mod
        # might publish FIGHTER_RETIRED without a date).
        sim_date = (
            event.get("current_date")
            or event.get("event_date")
        )
        if not sim_date:
            clock = conn.execute(
                "SELECT current_date FROM simulation_clock WHERE clock_id=1"
            ).fetchone()
            sim_date = clock[0] if clock else None
        if not sim_date:
            from datetime import date as _date
            sim_date = _date.today().isoformat()

        # ---- Induct ----
        conn.execute(
            "INSERT INTO hall_of_fame "
            "(fighter_id, inducted_date, career_summary, career_highlights) "
            "VALUES (?, ?, ?, ?)",
            (fighter_id, sim_date, career_summary, career_highlights)
        )

        # ---- Write induction news item ----
        # Uses the news engine's _write_news_item helper so the
        # induction news reads like a journalist's Hall of Fame
        # writeup (rich source, source-tone prefix) rather than a
        # bare wire-service item. topic='hall_of_fame' so future UI
        # filters can group HoF induction news together (separate
        # from the standard 'retirement' news the inline tick
        # processor already wrote).
        try:
            # Load the fighter's name for the headline.
            name_row = conn.execute(
                "SELECT first_name, last_name, nickname "
                "FROM fighters WHERE fighter_id=?",
                (fighter_id,),
            ).fetchone()
            if name_row:
                first, last, nick = name_row
                if nick:
                    fighter_name = f'{first} "{nick}" {last}'
                else:
                    fighter_name = f"{first} {last}"
            else:
                fighter_name = f"Fighter {fighter_id}"

            headline = f"{fighter_name} inducted into Hall of Fame"
            # The body uses the voice-layer career_summary — no raw
            # attribute numbers per CONVENTIONS §14.
            body = (
                f"{fighter_name} has been inducted into the Hall of "
                f"Fame, cementing their place among the legends of "
                f"the sport. {career_summary}"
            )

            # Use the news engine's _write_news_item helper if
            # available — it picks a rich news source, applies the
            # source's tone, and writes the item under our topic.
            try:
                from news import _write_news_item
                _write_news_item(
                    conn, headline, body,
                    sentiment="positive",
                    fighter_id=fighter_id,
                    published_at=sim_date,
                    rng=rng,
                    topic="hall_of_fame",
                )
            except ImportError:
                # news.py not available — fall back to a bare
                # INSERT INTO news_items using the 'System Feed'
                # source (mirrors app.write_news). Defensive —
                # shouldn't happen since news.py is a core module.
                src = conn.execute(
                    "SELECT news_source_id FROM news_sources "
                    "WHERE name='System Feed'"
                ).fetchone()
                src_id = src[0] if src else conn.execute(
                    "INSERT INTO news_sources "
                    "(name, credibility, sensationalism, bias, "
                    "regional_reach, reliability, frequency) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("System Feed", 70, 40, 50, 60, 80, 80),
                ).lastrowid
                conn.execute(
                    "INSERT INTO news_items "
                    "(news_source_id, headline, body, sentiment, "
                    "topic, fighter_id, published_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (src_id, headline, body, "positive",
                     "hall_of_fame", fighter_id, sim_date),
                )
        except Exception as e:
            # News write failed — don't crash the induction. The
            # hall_of_fame row is already inserted; the news item
            # is a nice-to-have. Print a warning so the operator
            # can investigate.
            print(f"WARNING: hof_svc.induce_fighter_into_hof: "
                  f"news write failed for fighter_id={fighter_id}: "
                  f"{type(e).__name__}: {e}",
                  file=sys.stderr)

    except Exception as e:
        # CONVENTIONS §15.4 — defensive subscriber. Catch all
        # exceptions, print a warning, don't crash the bus. The
        # bus itself also catches subscriber exceptions, but we
        # add our own try/except so the error message is more
        # informative (includes the fighter_id + module name).
        print(f"WARNING: hof_svc.induce_fighter_into_hof failed: "
              f"{type(e).__name__}: {e}",
              file=sys.stderr)


# ----------------------------------------------------------------
# Registration
# ----------------------------------------------------------------

def register_subscribers():
    """Register HoF induction subscriber on the event bus.

    Call once at startup (UI App.__init__, test setup, etc.). The
    function is safe to call multiple times — the event bus's
    subscribe() simply appends to its subscriber list. For test
    isolation, call reset_bus() first to clear any prior
    registrations.

    Registers:
      - induce_fighter_into_hof on Events.FIGHTER_RETIRED
        (published by tick_processor._check_retirements when a
        fighter retires on their birthday)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.FIGHTER_RETIRED, induce_fighter_into_hof,
        name="hof_svc.induce_fighter_into_hof",
    )
