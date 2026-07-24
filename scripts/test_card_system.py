#!/usr/bin/env python3
"""Acceptance test for Task FIX-CardSystem — full fight card system.

Tests the rewrite of `schedule_next_event` in src/app.py to build
FULL FIGHT CARDS (5-13 fights depending on promotion.size_tier)
with intelligent matchmaking, instead of the old 1-fight-per-event
behavior.

Test cases:
  A. schedule_next_event creates 5+ fights for small promotions
  B. schedule_next_event creates 7+ fights for mid promotions
  C. schedule_next_event creates 10+ fights for major promotions
  D. Main event is a title fight when champion is available
  E. Main event has 5 rounds (championship distance)
  F. Prelim fights have 3 rounds
  G. No fighter appears twice on the same card
  H. All fighters are from the same promotion
  I. No injured/suspended fighters booked
  J. Event is named "{Promotion} {N}: {FighterA} vs {FighterB}"
  K. Card slots are assigned correctly (main_event, co_main,
     featured_prelim, prelim)
  L. Training camps created for all booked fighters
  M. Rival AI: resolves one fight per tick from a multi-fight card
  N. Design Law (§13): Conflict (varied card) + Investment
     (card construction creates future storylines)

Pattern follows scripts/test_event_scheduler.py + test_career_arc_
rival_ai.py (CONVENTIONS §10 — dynamic version pattern, no
hardcoded version strings).

Run from the project root:
    python3 scripts/test_card_system.py

Exit code 0 = all PASS, 1 = any FAIL. The script rebuilds the DB at
`data/cage_empire.db` for each test case (case isolation).
"""
import os
import random
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call schedule_next_event() and
# resolve_next_fight() directly without going through the Tkinter UI.
sys.path.insert(0, str(SRC_DIR))

# Importing app.py pulls in tkinter. The import itself does not require
# a display (only tk.Tk() does), so this is safe in headless contexts.
import app  # noqa: E402

# Dynamic version pattern (CONVENTIONS §10) — read the schema version
# from build_db.CODE_SCHEMA_VERSION, no hardcoded strings.
import build_db  # noqa: E402
EXPECTED_CODE_VERSION = build_db.CODE_SCHEMA_VERSION
EXPECTED_MIGRATION_PREFIX = f"v{EXPECTED_CODE_VERSION.replace('.', '_')}_"

# Seeded values from src/seed_data.py — used for assertions.
SEEDED_EVENT_DATE = "2026-08-15"
DEFAULT_WEEKS_OUT = 4

# Card size ranges per the brief.
CARD_SIZE_RANGES = {
    'major': (10, 13),
    'mid':   (7, 9),
    'small': (5, 6),
}


def build_fresh_db():
    """Drop + rebuild + seed the DB so the test starts from a known state."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True,
        cwd=PROJECT_DIR,
        capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True,
        cwd=PROJECT_DIR,
        capture_output=True,
    )


def make_weight_class(conn, name, min_w, max_w):
    """Insert a weight class and return its id."""
    return conn.execute(
        "INSERT INTO weight_classes (name, gender, min_weight_kg, max_weight_kg) "
        "VALUES (?, 'male', ?, ?)",
        (name, min_w, max_w),
    ).lastrowid


def make_promo_with_fighters(conn, name, size_tier, n_per_wc, n_wcs=3,
                              gym_id=1, style_id=1, pers_id=1,
                              seed_aggression=60):
    """Create a promotion with `n_wcs` weight classes and `n_per_wc`
    fighters per WC. Returns (promo_id, [wc_ids]).

    Each weight class gets a vacant title. Each fighter gets:
      - fighter_attributes (default 50s)
      - fighter_personality (default 50s)
      - fighter_career with potential (50 + i*3)
      - rankings row with rating (950 + i*15 + wc_idx*20)

    The varied ratings give the matchmaking logic signal (top-rated
    fighters become main event / co-main; lower-rated become prelims).
    """
    promo_id = conn.execute(
        "INSERT INTO promotions (name, size_tier, nation_id, region_id, "
        "ai_aggression, ai_spending_style) VALUES (?, ?, ?, ?, ?, 'balanced')",
        (name, size_tier, 1, 1, seed_aggression),
    ).lastrowid
    # Use the seeded Lightweight (wc_id=1) as the first WC, then add more.
    wc_ids = [1]
    for i in range(1, n_wcs):
        wc_id = make_weight_class(conn, f"{name}_WC{i}", 60 + i * 5, 65 + i * 5)
        wc_ids.append(wc_id)
    for wc_id in wc_ids:
        conn.execute(
            "INSERT INTO titles (promotion_id, weight_class_id, is_vacant) "
            "VALUES (?, ?, 1)",
            (promo_id, wc_id),
        )
    for wc_idx, wc_id in enumerate(wc_ids):
        for i in range(n_per_wc):
            fid = conn.execute(
                "INSERT INTO fighters (first_name, last_name, nickname, "
                "gender, date_of_birth, birth_city_id, birth_nation_id, "
                "residence_city_id, residence_nation_id, weight_class_id, "
                "current_gym_id, current_promotion_id, "
                "fight_style_archetype_id, personality_archetype_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{name}_F{wc_idx}_{i}", "Last", "Nick", "male",
                 "1990-01-01", 1, 1, 1, 1, wc_id, gym_id, promo_id,
                 style_id, pers_id),
            ).lastrowid
            conn.execute(
                "INSERT INTO fighter_attributes (fighter_id) VALUES (?)",
                (fid,),
            )
            conn.execute(
                "INSERT INTO fighter_personality (fighter_id) VALUES (?)",
                (fid,),
            )
            conn.execute(
                "INSERT INTO fighter_career (fighter_id, potential) "
                "VALUES (?, ?)",
                (fid, 50 + i * 3),
            )
            rating = 950.0 + i * 15 + wc_idx * 20
            conn.execute(
                "INSERT INTO rankings (fighter_id, weight_class_id, "
                "promotion_id, rating) VALUES (?, ?, ?, ?)",
                (fid, wc_id, promo_id, rating),
            )
    conn.commit()
    return promo_id, wc_ids


def get_event_fights(conn, event_id):
    """Return list of (fight_id, card_slot, is_title_fight,
    scheduled_rounds, weight_class_id, card_position) for the event,
    ordered by card_position (ascending = main event first).
    """
    return conn.execute(
        "SELECT f.fight_id, f.card_slot, f.is_title_fight, "
        "f.scheduled_rounds, f.weight_class_id, ec.card_position "
        "FROM fights f JOIN event_cards ec ON ec.fight_id=f.fight_id "
        "WHERE f.event_id=? ORDER BY ec.card_position",
        (event_id,),
    ).fetchall()


def get_event_fighters(conn, event_id):
    """Return list of fighter_ids booked on the event."""
    rows = conn.execute(
        "SELECT DISTINCT fp.fighter_id FROM fight_participants fp "
        "JOIN fights f ON f.fight_id=fp.fight_id "
        "WHERE f.event_id=?",
        (event_id,),
    ).fetchall()
    return [r[0] for r in rows]


def main():
    sep = "=" * 80
    print(sep)
    print("FIX-CardSystem ACCEPTANCE TEST — full fight card system")
    print(sep)

    results = []

    def check(case, name, passed, detail=""):
        results.append((case, name, passed, detail))
        status = "PASS" if passed else "FAIL"
        # Truncate long detail lines for readability.
        detail_str = str(detail)
        if len(detail_str) > 60:
            detail_str = detail_str[:57] + "..."
        print(f"  [{status}] {case} {name}")
        if not passed:
            print(f"          detail: {detail}")

    # ----------------------------------------------------------------
    # Schema version sanity check (CONVENTIONS §10 — dynamic version).
    # ----------------------------------------------------------------
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    sv = conn.execute(
        "SELECT schema_version FROM schema_meta WHERE schema_name='cage_empire'"
    ).fetchone()
    check("S", "schema_meta.schema_version matches build_db.CODE_SCHEMA_VERSION",
          sv is not None and sv[0] == EXPECTED_CODE_VERSION,
          f"got={sv[0] if sv else None}, expected={EXPECTED_CODE_VERSION}")
    conn.close()

    # ----------------------------------------------------------------
    # Case A — schedule_next_event creates 5+ fights for small promos.
    # ----------------------------------------------------------------
    print("\n--- Case A: small promotion gets 5+ fights ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Small promo with 6 fighters per WC × 3 WCs = 18 fighters.
    # target_min=5, target_max=6. 18 fighters / 2 = 9 fights max,
    # so the card should fill to target_max=6.
    promo_id, _ = make_promo_with_fighters(
        conn, "SmallBash", "small", n_per_wc=6, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    check("A", "schedule_next_event returned an event_id",
          event_id is not None and isinstance(event_id, int),
          f"got={event_id}")
    if event_id:
        n_fights = conn.execute(
            "SELECT COUNT(*) FROM fights WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        lo, hi = CARD_SIZE_RANGES['small']
        check("A", f"small promo has {lo}-{hi} fights (got {n_fights})",
              lo <= n_fights <= hi,
              f"got={n_fights}, expected {lo}-{hi}")
    conn.close()

    # ----------------------------------------------------------------
    # Case B — schedule_next_event creates 7+ fights for mid promos.
    # ----------------------------------------------------------------
    print("\n--- Case B: mid promotion gets 7+ fights ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "MidBash", "mid", n_per_wc=8, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    check("B", "schedule_next_event returned an event_id",
          event_id is not None, f"got={event_id}")
    if event_id:
        n_fights = conn.execute(
            "SELECT COUNT(*) FROM fights WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        lo, hi = CARD_SIZE_RANGES['mid']
        check("B", f"mid promo has {lo}-{hi} fights (got {n_fights})",
              lo <= n_fights <= hi,
              f"got={n_fights}, expected {lo}-{hi}")
    conn.close()

    # ----------------------------------------------------------------
    # Case C — schedule_next_event creates 10+ fights for major promos.
    # ----------------------------------------------------------------
    print("\n--- Case C: major promotion gets 10+ fights ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "BigBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    check("C", "schedule_next_event returned an event_id",
          event_id is not None, f"got={event_id}")
    if event_id:
        n_fights = conn.execute(
            "SELECT COUNT(*) FROM fights WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        lo, hi = CARD_SIZE_RANGES['major']
        check("C", f"major promo has {lo}-{hi} fights (got {n_fights})",
              lo <= n_fights <= hi,
              f"got={n_fights}, expected {lo}-{hi}")
    conn.close()

    # ----------------------------------------------------------------
    # Case D — main event is a title fight when champion is available.
    # ----------------------------------------------------------------
    print("\n--- Case D: main event is a title fight when champion available ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Major promo with 12 fighters per WC × 3 WCs + vacant titles.
    promo_id, wc_ids = make_promo_with_fighters(
        conn, "ChampBash", "major", n_per_wc=12, n_wcs=3)
    # Resolve the first fight to make someone a champion — then the
    # next auto-scheduled main event should be a title DEFENSE.
    random.seed(42)
    # First, schedule an event with a vacant title main event.
    event_id_1 = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    # The main event on event 1 should be a title fight (vacant title).
    me_fight = conn.execute(
        "SELECT f.fight_id, f.is_title_fight, f.card_slot "
        "FROM fights f JOIN event_cards ec ON ec.fight_id=f.fight_id "
        "WHERE f.event_id=? AND ec.card_position=1",
        (event_id_1,),
    ).fetchone()
    check("D", "event 1 main event is a title fight (vacant title)",
          me_fight is not None and me_fight[1] == 1,
          f"got={me_fight}")
    if me_fight:
        # Resolve the main event so a champion is crowned. Pass
        # promotion_id to filter to this promo's fights (the seeded
        # AC event has 1 unresolved fight that would otherwise be
        # picked first by resolve_next_fight).
        random.seed(42)
        app.resolve_next_fight(conn, promotion_id=promo_id)
        conn.commit()
        # Check any title for this promo has a champion.
        any_champion = conn.execute(
            "SELECT COUNT(*) FROM titles WHERE promotion_id=? "
            "AND is_vacant=0 AND current_champion_fighter_id IS NOT NULL",
            (promo_id,),
        ).fetchone()[0]
        check("D", "at least one title has a champion after resolve",
              any_champion >= 1, f"champions={any_champion}")
        # The next auto-scheduled event's main event should be a title
        # defense (champion vs contender).
        new_event = conn.execute(
            "SELECT event_id FROM events WHERE promotion_id=? "
            "AND status='scheduled' ORDER BY event_id DESC LIMIT 1",
            (promo_id,),
        ).fetchone()
        if new_event:
            new_event_id = new_event[0]
            new_me = conn.execute(
                "SELECT f.fight_id, f.is_title_fight, f.card_slot "
                "FROM fights f JOIN event_cards ec ON ec.fight_id=f.fight_id "
                "WHERE f.event_id=? AND ec.card_position=1",
                (new_event_id,),
            ).fetchone()
            check("D", "next event main event is a title fight (champion defense)",
                  new_me is not None and new_me[1] == 1,
                  f"got={new_me}")
            if new_me:
                # Verify the champion is in the new main event.
                champ_id = conn.execute(
                    "SELECT current_champion_fighter_id FROM titles "
                    "WHERE promotion_id=? AND is_vacant=0 "
                    "AND current_champion_fighter_id IS NOT NULL LIMIT 1",
                    (promo_id,),
                ).fetchone()
                if champ_id:
                    parts = [r[0] for r in conn.execute(
                        "SELECT fighter_id FROM fight_participants "
                        "WHERE fight_id=?", (new_me[0],)
                    ).fetchall()]
                    check("D", "champion is in the title defense fight",
                          champ_id[0] in parts,
                          f"champion={champ_id[0]}, participants={parts}")
    conn.close()

    # ----------------------------------------------------------------
    # Case E — main event has 5 rounds (championship distance).
    # ----------------------------------------------------------------
    print("\n--- Case E: main event has 5 rounds ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "RoundsBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fights = get_event_fights(conn, event_id)
    main_event = next((f for f in fights if f[1] == 'main_event'), None)
    check("E", "main event exists",
          main_event is not None, f"fights={fights}")
    if main_event:
        check("E", "main event has 5 scheduled_rounds (championship distance)",
              main_event[3] == 5, f"got={main_event[3]}")
    conn.close()

    # ----------------------------------------------------------------
    # Case F — prelim fights have 3 rounds.
    # ----------------------------------------------------------------
    print("\n--- Case F: prelim fights have 3 rounds ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "PrelimBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fights = get_event_fights(conn, event_id)
    prelim_fights = [f for f in fights if f[1] == 'prelim']
    check("F", "at least 1 prelim fight exists",
          len(prelim_fights) >= 1, f"count={len(prelim_fights)}")
    all_3_rounds = all(f[3] == 3 for f in prelim_fights)
    check("F", "all prelim fights have 3 scheduled_rounds",
          len(prelim_fights) >= 1 and all_3_rounds,
          f"rounds={[f[3] for f in prelim_fights]}")
    # Also check co_main and featured_prelim are 3 rounds.
    co_main_fights = [f for f in fights if f[1] == 'co_main']
    if co_main_fights:
        check("F", "co-main has 3 scheduled_rounds",
              all(f[3] == 3 for f in co_main_fights),
              f"rounds={[f[3] for f in co_main_fights]}")
    fp_fights = [f for f in fights if f[1] == 'featured_prelim']
    if fp_fights:
        check("F", "featured prelims have 3 scheduled_rounds",
              all(f[3] == 3 for f in fp_fights),
              f"rounds={[f[3] for f in fp_fights]}")
    conn.close()

    # ----------------------------------------------------------------
    # Case G — no fighter appears twice on the same card.
    # ----------------------------------------------------------------
    print("\n--- Case G: no fighter appears twice on the same card ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "UniqueBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fight_ids = [r[0] for r in conn.execute(
        "SELECT fight_id FROM fights WHERE event_id=?", (event_id,)
    ).fetchall()]
    # Get all fighter appearances (with multiplicity).
    all_appearances = []
    for fid in fight_ids:
        parts = [r[0] for r in conn.execute(
            "SELECT fighter_id FROM fight_participants WHERE fight_id=?",
            (fid,),
        ).fetchall()]
        all_appearances.extend(parts)
    unique_fighters = set(all_appearances)
    check("G", "no fighter appears twice on the same card",
          len(all_appearances) == len(unique_fighters),
          f"appearances={len(all_appearances)}, unique={len(unique_fighters)}")
    conn.close()

    # ----------------------------------------------------------------
    # Case H — all fighters are from the same promotion.
    # ----------------------------------------------------------------
    print("\n--- Case H: all fighters from the same promotion ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "SamePromoBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fighter_ids = get_event_fighters(conn, event_id)
    distinct_promos = conn.execute(
        "SELECT COUNT(DISTINCT current_promotion_id) FROM fighters "
        "WHERE fighter_id IN ({})".format(
            ",".join("?" * len(fighter_ids))),
        fighter_ids,
    ).fetchone()[0]
    check("H", "all booked fighters are from the same promotion",
          distinct_promos == 1,
          f"distinct_promos={distinct_promos}, expected=1")
    # Also verify the promo id matches.
    actual_promo = conn.execute(
        "SELECT DISTINCT current_promotion_id FROM fighters "
        "WHERE fighter_id IN ({})".format(
            ",".join("?" * len(fighter_ids))),
        fighter_ids,
    ).fetchone()
    check("H", "booked fighters' promotion matches the scheduled promotion",
          actual_promo is not None and actual_promo[0] == promo_id,
          f"actual={actual_promo[0] if actual_promo else None}, "
          f"expected={promo_id}")
    conn.close()

    # ----------------------------------------------------------------
    # Case I — no injured/suspended fighters booked.
    # ----------------------------------------------------------------
    print("\n--- Case I: no injured/suspended fighters booked ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, wc_ids = make_promo_with_fighters(
        conn, "CleanBash", "major", n_per_wc=12, n_wcs=3)
    # Injure 2 fighters and suspend 1 fighter on the roster.
    fighters_to_injure = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=? "
        "ORDER BY fighter_id LIMIT 2", (promo_id,)
    ).fetchall()
    for (fid,) in fighters_to_injure:
        conn.execute(
            "INSERT INTO injuries (fighter_id, injury_type, severity, "
            "body_area, start_date, projected_return_date, is_active) "
            "VALUES (?, 'test_injury', 5, 'general', '2026-07-01', "
            "'2026-12-01', 1)",
            (fid,),
        )
    fighter_to_suspend = conn.execute(
        "SELECT fighter_id FROM fighters WHERE current_promotion_id=? "
        "ORDER BY fighter_id LIMIT 1 OFFSET 2", (promo_id,)
    ).fetchone()
    if fighter_to_suspend:
        conn.execute(
            "INSERT INTO suspensions (fighter_id, suspension_type, "
            "start_date, end_date, duration_days, description, is_active) "
            "VALUES (?, 'behavior', '2026-07-01', '2026-12-01', 180, "
            "'test suspension', 1)",
            (fighter_to_suspend[0],),
        )
    conn.commit()
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fighter_ids = get_event_fighters(conn, event_id)
    # No booked fighter should be in the injuries table (is_active=1).
    injured_booked = conn.execute(
        "SELECT COUNT(*) FROM injuries WHERE is_active=1 AND fighter_id IN ({})".format(
            ",".join("?" * len(fighter_ids))),
        fighter_ids,
    ).fetchone()[0]
    check("I", "no booked fighter has an active injury",
          injured_booked == 0, f"injured_booked={injured_booked}")
    # No booked fighter should be in the suspensions table (is_active=1).
    suspended_booked = conn.execute(
        "SELECT COUNT(*) FROM suspensions WHERE is_active=1 AND fighter_id IN ({})".format(
            ",".join("?" * len(fighter_ids))),
        fighter_ids,
    ).fetchone()[0]
    check("I", "no booked fighter has an active suspension",
          suspended_booked == 0, f"suspended_booked={suspended_booked}")
    conn.close()

    # ----------------------------------------------------------------
    # Case J — event is named "{Promotion} {N}: {FighterA} vs {FighterB}".
    # ----------------------------------------------------------------
    print("\n--- Case J: event name format ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "NameBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    event_name = conn.execute(
        "SELECT event_name FROM events WHERE event_id=?",
        (event_id,),
    ).fetchone()[0]
    # Format: "{Promotion} {N}: {FighterA} vs {FighterB}"
    main_event = next((f for f in get_event_fights(conn, event_id)
                       if f[1] == 'main_event'), None)
    if main_event:
        me_parts = [r[0] for r in conn.execute(
            "SELECT fighter_id FROM fight_participants WHERE fight_id=?",
            (main_event[0],)
        ).fetchall()]
        if len(me_parts) == 2:
            me_a_name = conn.execute(
                "SELECT first_name || ' ' || last_name FROM fighters "
                "WHERE fighter_id=?", (me_parts[0],)
            ).fetchone()[0]
            me_b_name = conn.execute(
                "SELECT first_name || ' ' || last_name FROM fighters "
                "WHERE fighter_id=?", (me_parts[1],)
            ).fetchone()[0]
            # The event_name uses fighter_a (top-rated) first, which
            # may be either of the 2 participants depending on which
            # one is the higher-rated (the order in fight_participants
            # is by fighter_id, not by corner). Accept either ordering.
            expected_name_1 = f"NameBash 1: {me_a_name} vs {me_b_name}"
            expected_name_2 = f"NameBash 1: {me_b_name} vs {me_a_name}"
            check("J", f"event_name matches format (either fighter order)",
                  event_name in (expected_name_1, expected_name_2),
                  f"got={event_name!r}, expected={expected_name_1!r} "
                  f"or {expected_name_2!r}")
            check("J", "event_name contains ' vs '",
                  " vs " in event_name, f"name={event_name!r}")
            check("J", "event_name contains promotion name",
                  "NameBash" in event_name, f"name={event_name!r}")
            check("J", "event_name contains event number (1)",
                  "NameBash 1:" in event_name, f"name={event_name!r}")
    conn.close()

    # ----------------------------------------------------------------
    # Case K — card slots assigned correctly.
    # ----------------------------------------------------------------
    print("\n--- Case K: card slots assigned correctly ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "SlotsBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fights = get_event_fights(conn, event_id)
    slots = [f[1] for f in fights]
    valid_slots = {'main_event', 'co_main', 'featured_prelim', 'prelim'}
    check("K", "all card_slot values are in the allowed set",
          all(s in valid_slots for s in slots),
          f"slots={slots}")
    check("K", "exactly 1 main_event",
          slots.count('main_event') == 1,
          f"main_event_count={slots.count('main_event')}")
    check("K", "at most 1 co_main",
          slots.count('co_main') <= 1,
          f"co_main_count={slots.count('co_main')}")
    # Check card_position is sequential 1..N
    positions = [f[5] for f in fights]
    expected_positions = list(range(1, len(fights) + 1))
    check("K", "card_position is sequential 1..N",
          positions == expected_positions,
          f"positions={positions}, expected={expected_positions}")
    # Check main_event is at position 1 (card_position=1).
    main_at_pos_1 = next((f for f in fights if f[5] == 1), None)
    check("K", "card_position=1 is the main event",
          main_at_pos_1 is not None and main_at_pos_1[1] == 'main_event',
          f"pos_1_fight={main_at_pos_1}")
    # Check event_cards.is_main_event=1 for main_event, is_co_main=1 for co_main.
    main_ec = conn.execute(
        "SELECT is_main_event, is_co_main FROM event_cards ec "
        "JOIN fights f ON f.fight_id=ec.fight_id "
        "WHERE f.event_id=? AND f.card_slot='main_event'",
        (event_id,),
    ).fetchone()
    check("K", "main_event fight has is_main_event=1 in event_cards",
          main_ec is not None and main_ec[0] == 1,
          f"row={main_ec}")
    co_main_ec = conn.execute(
        "SELECT is_main_event, is_co_main FROM event_cards ec "
        "JOIN fights f ON f.fight_id=ec.fight_id "
        "WHERE f.event_id=? AND f.card_slot='co_main'",
        (event_id,),
    ).fetchone()
    if co_main_ec:
        check("K", "co_main fight has is_co_main=1 in event_cards",
              co_main_ec[1] == 1, f"row={co_main_ec}")
    conn.close()

    # ----------------------------------------------------------------
    # Case L — training camps created for all booked fighters.
    # ----------------------------------------------------------------
    print("\n--- Case L: training camps created for all booked fighters ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "CampBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fighter_ids = get_event_fighters(conn, event_id)
    n_camps = conn.execute(
        "SELECT COUNT(*) FROM training_camps WHERE event_id=?",
        (event_id,),
    ).fetchone()[0]
    check("L", "training camps created for all booked fighters",
          n_camps == len(fighter_ids),
          f"camps={n_camps}, fighters={len(fighter_ids)}")
    # Each camp should be tied to a fight on this event.
    camp_fights = conn.execute(
        "SELECT DISTINCT fight_id FROM training_camps WHERE event_id=?",
        (event_id,),
    ).fetchall()
    event_fights = conn.execute(
        "SELECT fight_id FROM fights WHERE event_id=?",
        (event_id,),
    ).fetchall()
    camp_fight_ids = {r[0] for r in camp_fights}
    event_fight_ids = {r[0] for r in event_fights}
    check("L", "all camp fight_ids are on this event",
          camp_fight_ids.issubset(event_fight_ids),
          f"camp_fights={camp_fight_ids}, event_fights={event_fight_ids}")
    conn.close()

    # ----------------------------------------------------------------
    # Case M — rival AI: resolves one fight per tick from a multi-fight card.
    # ----------------------------------------------------------------
    print("\n--- Case M: rival AI resolves 1 fight per tick from multi-fight card ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Create a rival promotion with enough fighters for a multi-fight card.
    # Use a promo_id > 1 so it's a "rival" (not the player's AC promo_id=1).
    rfl2_id, _ = make_promo_with_fighters(
        conn, "RivalRFL", "mid", n_per_wc=8, n_wcs=3,
        seed_aggression=60)
    # Manually schedule a multi-fight event for RFL2.
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, rfl2_id, from_event_date="2026-07-21", weeks_out=0)
    conn.commit()
    n_fights = conn.execute(
        "SELECT COUNT(*) FROM fights WHERE event_id=?",
        (event_id,),
    ).fetchone()[0]
    check("M", "scheduled event has multiple fights",
          n_fights >= 2, f"n_fights={n_fights}")
    n_unresolved_before = conn.execute(
        "SELECT COUNT(*) FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE e.promotion_id=? AND f.winner_fighter_id IS NULL "
        "AND f.result_type IS NULL",
        (rfl2_id,),
    ).fetchone()[0]
    check("M", f"rival promo has {n_unresolved_before} unresolved fights before tick",
          n_unresolved_before >= 2,
          f"count={n_unresolved_before}")
    # Run rival AI on a weekly tick.
    from event_bus import get_bus, Events, reset_bus
    import rival_ai
    reset_bus()
    rival_ai.register_subscribers()
    # Set sim clock to a weekly tick (current_day % 7 == 0).
    conn.execute(
        "UPDATE simulation_clock SET current_day=7, "
        "current_date='2026-07-27' WHERE clock_id=1"
    )
    conn.commit()
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.TICK_ADVANCED,
        'current_date': '2026-07-27',
        'current_day': 7,
    })
    conn.commit()
    n_unresolved_after = conn.execute(
        "SELECT COUNT(*) FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE e.promotion_id=? AND f.winner_fighter_id IS NULL "
        "AND f.result_type IS NULL",
        (rfl2_id,),
    ).fetchone()[0]
    resolved_count = n_unresolved_before - n_unresolved_after
    check("M", "rival AI resolved exactly 1 fight per weekly tick",
          resolved_count == 1,
          f"before={n_unresolved_before}, after={n_unresolved_after}, "
          f"resolved={resolved_count}")
    conn.close()

    # ----------------------------------------------------------------
    # Case N — Design Law (§13): Conflict + Investment.
    # ----------------------------------------------------------------
    print("\n--- Case N: Design Law (§13) — Conflict + Investment ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    promo_id, _ = make_promo_with_fighters(
        conn, "DesignBash", "major", n_per_wc=12, n_wcs=3)
    random.seed(42)
    event_id = app.schedule_next_event(
        conn, promo_id, from_event_date=SEEDED_EVENT_DATE,
        weeks_out=DEFAULT_WEEKS_OUT)
    conn.commit()
    fights = get_event_fights(conn, event_id)
    # Conflict (§13.1): the card has varied fights — main event,
    # co-main, featured prelims, prelims. This creates multiple
    # concurrent storylines (the champion defending, contenders
    # jockeying, prospects developing).
    slot_counts = {}
    for f in fights:
        slot_counts[f[1]] = slot_counts.get(f[1], 0) + 1
    check("N", "Conflict: card has multiple slot types (varied card)",
          len(slot_counts) >= 3,
          f"slot_counts={slot_counts}")
    # Conflict: card uses multiple weight classes (variety).
    wc_ids_used = set(f[4] for f in fights)
    check("N", "Conflict: card uses multiple weight classes (variety)",
          len(wc_ids_used) >= 2,
          f"wc_ids_used={wc_ids_used}")
    # Investment (§13.1): the card construction creates future
    # storylines — the main event determines the next title
    # challenger, the prelims develop prospects. The training camps
    # (verified in Case L) are the literal "investment" system.
    n_prospects = 0
    for f in fights:
        if f[1] == 'prelim':
            # Check the fighters' potential — high-potential fighters
            # on the prelims is the "prospect development" storyline.
            parts = [r[0] for r in conn.execute(
                "SELECT fighter_id FROM fight_participants WHERE fight_id=?",
                (f[0],),
            ).fetchall()]
            for fid in parts:
                pot = conn.execute(
                    "SELECT potential FROM fighter_career WHERE fighter_id=?",
                    (fid,),
                ).fetchone()
                if pot and pot[0] >= 60:
                    n_prospects += 1
    check("N", "Investment: at least 1 high-potential prospect on prelims",
          n_prospects >= 1,
          f"n_prospects={n_prospects}")
    # Investment: the main event is a title fight (creates a future
    # champion storyline — the Kingmaker fantasy).
    main_event = next((f for f in fights if f[1] == 'main_event'), None)
    check("N", "Investment: main event is a title fight (Kingmaker fantasy)",
          main_event is not None and main_event[2] == 1,
          f"main_event={main_event}")
    conn.close()

    # ----------------------------------------------------------------
    # Print summary.
    # ----------------------------------------------------------------
    print("\n" + sep)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print(sep)
    print("By case:")
    by_case = {}
    for case, name, passed, detail in results:
        by_case.setdefault(case, {"pass": 0, "fail": 0})
        if passed:
            by_case[case]["pass"] += 1
        else:
            by_case[case]["fail"] += 1
    for case in sorted(by_case.keys()):
        c = by_case[case]
        print(f"  Case {case}: {c['pass']} PASS, {c['fail']} FAIL")
    print(sep)

    if n_fail == 0:
        print("OVERALL: PASS")
        sys.exit(0)
    else:
        print("OVERALL: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
