#!/usr/bin/env python3
"""Acceptance test for Task ID 23 — News Engine (no schema change).

Tests the event-bus-driven, voice-layer-driven news engine that
replaces hardcoded fight-result strings with varied, context-aware,
journalistic headlines + bodies. The engine subscribes to
FIGHT_RESOLVED, TITLE_CHANGED, and TICK_ADVANCED on the event bus
(CONVENTIONS §15) and writes news_engine topic items to the existing
news_items table.

  A. News engine module imports correctly
  B. generate_fight_news produces varied headlines (≥3 over 10 calls)
  C. No raw numbers in any news text (CONVENTIONS §14)
  D. Event bus integration: FIGHT_RESOLVED triggers news generation
  E. Title change news generated on TITLE_CHANGED event
  F. News uses fighter names + voice descriptors
  G. Design Law (§13): stories, anticipation, legacy

Exit code: 0 = all PASS, 1 = any FAIL.
"""
import re
import sys
import sqlite3
import subprocess
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
sys.path.insert(0, str(SRC_DIR))

import app  # noqa: E402
import news  # noqa: E402
import build_db  # noqa: E402
from event_bus import get_bus, reset_bus, Events  # noqa: E402

EXPECTED_VERSION = build_db.CODE_SCHEMA_VERSION

# Voice descriptor keywords — phrases the voice layer (Task 19) uses
# to describe attributes, career stages, and personality traits.
# Test F checks that at least one of these appears in each news body.
_VOICE_KEYWORDS = [
    # Tier words (CONVENTIONS §14.3)
    "elite", "strong", "capable", "above-average", "respectable",
    "serviceable", "average", "limited", "poor", "abysmal",
    # Career-stage words (voice.describe_career_stage)
    "champion", "titleholder", "prospect", "veteran", "contender",
    "journeyman", "gatekeeper", "competitor", "fighter",
    # Attribute-flavor words (sample from voice.ATTRIBUTE_DESCRIPTORS)
    "power", "chin", "cardio", "footwork", "wrestling", "submission",
    "takedown", "clinch", "speed", "strength", "durability",
    "flexibility", "accuracy", "guard", "sprawl", "striker", "grappler",
    # Tier-word compounds commonly produced by describe_attribute
    "knockout", "submissions", "kicks", "striking",
]

# Digit regex — CONVENTIONS §14 forbids raw numbers in player-facing
# text. Word forms ("first", "one", "three") are allowed; digit
# characters ("1", "47") are not.
_DIGIT_RE = re.compile(r"[0-9]")

results = []


def check(case, name, passed, detail=""):
    results.append((case, name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  {case}  {name:<70} {status}  {detail}")


def build_fresh_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run([sys.executable, str(SRC_DIR / "build_db.py")],
                   check=True, cwd=PROJECT_DIR)
    subprocess.run([sys.executable, str(SRC_DIR / "seed_data.py")],
                   check=True, cwd=PROJECT_DIR)


def _resolve_seeded_fight(conn, seed=42):
    """Resolve the seeded title fight (John Vale vs Marcus Reed).

    Resets the bus, registers news engine subscribers, resolves the
    fight, commits. Returns the fight_id.
    """
    reset_bus()
    news.register_subscribers()
    random.seed(seed)
    fid = app.resolve_next_fight(conn)
    conn.commit()
    return fid


# ----------------------------------------------------------------
# Case A — module imports
# ----------------------------------------------------------------

def case_a_imports():
    """Verify news.py imports cleanly and exposes the required API."""
    print("\n--- Case A: module imports ---")
    check("A", "news module imports", news is not None, "")
    check("A", "NEWS_TOPIC constant exists",
          hasattr(news, "NEWS_TOPIC") and news.NEWS_TOPIC == "news_engine",
          f"got={getattr(news, 'NEWS_TOPIC', None)}")
    for fn_name in ("generate_fight_news", "generate_title_news",
                    "generate_injury_news", "generate_retirement_news",
                    "register_subscribers"):
        check("A", f"function '{fn_name}' exists",
              callable(getattr(news, fn_name, None)), "")


# ----------------------------------------------------------------
# Case B — headline variety
# ----------------------------------------------------------------

def case_b_variety():
    """generate_fight_news produces ≥3 distinct headlines over 10 calls."""
    print("\n--- Case B: headline variety ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    mock_event = {
        "type": Events.FIGHT_RESOLVED,
        "fight_id": 1,
        "event_id": 1,
        "promotion_id": 1,
        "weight_class_id": 1,
        "winner_id": 1,
        "loser_id": 2,
        "fighter_a_id": 1,
        "fighter_b_id": 2,
        "result_type": "ko_tko",
        "finish_round": 1,
        "finish_time": "1:23",
        "is_title_fight": 1,
        "title_changed": True,
        "event_date": "2026-08-15",
        "importance": 75,
    }
    # Call generate_fight_news 10 times directly (NOT via the bus).
    # Each call uses a fresh RNG so the template pick varies.
    for _ in range(10):
        news.generate_fight_news(conn, mock_event)
    conn.commit()
    headlines = [r[0] for r in conn.execute(
        "SELECT headline FROM news_items WHERE topic='news_engine' "
        "ORDER BY news_item_id"
    ).fetchall()]
    unique = set(headlines)
    check("B", "10 calls wrote 10 news items",
          len(headlines) == 10, f"got={len(headlines)}")
    check("B", "at least 3 unique headlines produced",
          len(unique) >= 3, f"got={len(unique)} unique")
    if unique:
        print(f"      unique headlines: {len(unique)}")
        for h in sorted(unique):
            print(f"        - {h}")
    conn.close()


# ----------------------------------------------------------------
# Case C — no raw numbers (CONVENTIONS §14)
# ----------------------------------------------------------------

def case_c_no_raw_numbers():
    """Verify no digit characters in any news_engine headline or body."""
    print("\n--- Case C: no raw numbers ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    _resolve_seeded_fight(conn)
    items = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='news_engine'"
    ).fetchall()
    check("C", "news_engine items generated", len(items) > 0,
          f"got={len(items)}")
    if not items:
        conn.close()
        return
    all_clean = True
    for h, b in items:
        if _DIGIT_RE.search(h):
            check("C", f"headline has no digits: {h!r}",
                  False, "digit found")
            all_clean = False
        if _DIGIT_RE.search(b):
            check("C", f"body has no digits: {b[:60]!r}...",
                  False, "digit found")
            all_clean = False
    if all_clean:
        check("C", "no raw digit characters in any news_engine item",
              True, f"checked {len(items)} items")
    conn.close()


# ----------------------------------------------------------------
# Case D — FIGHT_RESOLVED triggers news generation
# ----------------------------------------------------------------

def case_d_fight_resolved_triggers():
    """FIGHT_RESOLVED event triggers generate_fight_news via the bus."""
    print("\n--- Case D: FIGHT_RESOLVED triggers news ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    _resolve_seeded_fight(conn)
    fight_news = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='news_engine' "
        "AND fight_id IS NOT NULL"
    ).fetchall()
    check("D", "news_engine items generated for the resolved fight",
          len(fight_news) > 0, f"got={len(fight_news)}")
    # The bus should have triggered BOTH generate_fight_news AND
    # generate_injury_news (if any injuries were created). Both
    # subscribers fire on FIGHT_RESOLVED per news.register_subscribers.
    bus = get_bus()
    n_fight_subs = bus.subscriber_count(Events.FIGHT_RESOLVED)
    check("D", "≥2 FIGHT_RESOLVED subscribers (fight + injury)",
          n_fight_subs >= 2, f"got={n_fight_subs}")
    conn.close()


# ----------------------------------------------------------------
# Case E — TITLE_CHANGED triggers title news
# ----------------------------------------------------------------

def case_e_title_changed_triggers():
    """TITLE_CHANGED event triggers generate_title_news via the bus."""
    print("\n--- Case E: TITLE_CHANGED triggers title news ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    # Capture TITLE_CHANGED events to verify the bus fired them.
    reset_bus()
    news.register_subscribers()
    title_events = []
    bus = get_bus()
    bus.subscribe(Events.TITLE_CHANGED,
                  lambda c, e: title_events.append(e),
                  name="test_capture")
    random.seed(42)
    app.resolve_next_fight(conn)
    conn.commit()
    # The seeded fight is a title fight (is_title_fight=1, vacant
    # title) — TITLE_CHANGED should fire when the winner claims it.
    check("E", "TITLE_CHANGED event was published (seeded title fight)",
          len(title_events) >= 1, f"got={len(title_events)}")
    # Check for title-flavored news_engine items
    title_news = conn.execute(
        "SELECT headline FROM news_items WHERE topic='news_engine' "
        "AND (headline LIKE '%CHAMPION%' OR headline LIKE '%title%' "
        "OR headline LIKE '%belt%' OR headline LIKE '%crown%' "
        "OR headline LIKE '%throne%' OR headline LIKE '%gold%')"
    ).fetchall()
    check("E", "title-themed news_engine item generated",
          len(title_news) > 0, f"got={len(title_news)}")
    if title_news:
        print(f"      title headline: {title_news[0][0]}")
    conn.close()


# ----------------------------------------------------------------
# Case F — fighter names + voice descriptors
# ----------------------------------------------------------------

def case_f_voice_descriptors():
    """Verify news uses fighter names + voice layer descriptors."""
    print("\n--- Case F: fighter names + voice descriptors ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    _resolve_seeded_fight(conn)
    items = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='news_engine'"
    ).fetchall()
    check("F", "news_engine items exist for voice check",
          len(items) > 0, f"got={len(items)}")
    if not items:
        conn.close()
        return

    # The seeded fight is John Vale vs Marcus Reed — at least one
    # of those last names should appear in any fight-themed item.
    name_hits = 0
    voice_hits = 0
    for h, b in items:
        text = (h + " " + b).lower()
        if "vale" in text or "reed" in text:
            name_hits += 1
        if any(kw in text for kw in _VOICE_KEYWORDS):
            voice_hits += 1
    check("F", "every news_engine item references a fighter name",
          name_hits == len(items),
          f"got={name_hits}/{len(items)}")
    check("F", "every news_engine item uses at least one voice descriptor",
          voice_hits == len(items),
          f"got={voice_hits}/{len(items)}")
    # Spot-check that the headline includes a fighter name (journalistic
    # voice — real MMA headlines name the fighters).
    headlines_with_name = sum(
        1 for h, _ in items
        if "vale" in h.lower() or "reed" in h.lower()
    )
    check("F", "most headlines include a fighter name",
          headlines_with_name >= len(items) // 2,
          f"got={headlines_with_name}/{len(items)}")
    conn.close()


# ----------------------------------------------------------------
# Case G — Design Law (§13): stories, anticipation, legacy
# ----------------------------------------------------------------

def case_g_design_law():
    """Design Law check — news engine generates stories."""
    print("\n--- Case G: Design Law (§13) ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    fid = _resolve_seeded_fight(conn)

    # Conflict pillar — fight news tells the story of the bout.
    fight_news = conn.execute(
        "SELECT body FROM news_items WHERE topic='news_engine' "
        "AND fight_id=?", (fid,)
    ).fetchall()
    check("G", "Conflict: fight news tells the bout's story",
          len(fight_news) > 0, f"got={len(fight_news)}")

    # Anticipation pillar — title news hints at the division's future.
    title_news = conn.execute(
        "SELECT body FROM news_items WHERE topic='news_engine' "
        "AND (body LIKE '%era%' OR body LIKE '%contenders%' "
        "OR body LIKE '%division%' OR body LIKE '%crown%' "
        "OR body LIKE '%throne%' OR body LIKE '%echo%')"
    ).fetchall()
    check("G", "Anticipation: title news hints at division's future",
          len(title_news) > 0, f"got={len(title_news)}")

    # Legacy pillar — career stage descriptors + reign phrase provide
    # the fighter's place in history.
    legacy_news = conn.execute(
        "SELECT body FROM news_items WHERE topic='news_engine' "
        "AND (body LIKE '%career%' OR body LIKE '%titleholder%' "
        "OR body LIKE '%champion%' OR body LIKE '%veteran%' "
        "OR body LIKE '%prospect%' OR body LIKE '%competitor%')"
    ).fetchall()
    check("G", "Legacy: news uses career-stage descriptors",
          len(legacy_news) > 0, f"got={len(legacy_news)}")

    # Stories pillar — multiple news items per fight create a
    # narrative (fight result + injury + title change all tell
    # different facets of the same story).
    total_news = conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='news_engine' "
        "AND fight_id=?", (fid,)
    ).fetchone()[0]
    check("G", "Stories: ≥2 news items per resolved fight (multi-faceted)",
          total_news >= 2, f"got={total_news}")

    # Voice layer (§14) — no raw numbers in any of the stories.
    all_items = conn.execute(
        "SELECT headline, body FROM news_items WHERE topic='news_engine'"
    ).fetchall()
    clean = all(
        not _DIGIT_RE.search(h) and not _DIGIT_RE.search(b)
        for h, b in all_items
    )
    check("G", "Voice layer (§14): no raw numbers in stories",
          clean, f"checked {len(all_items)} items")

    # Event-bus driven (§15) — verify subscribers are registered (no
    # inline side effects were added to resolve_next_fight).
    bus = get_bus()
    has_fight = bus.subscriber_count(Events.FIGHT_RESOLVED) >= 2
    has_title = bus.subscriber_count(Events.TITLE_CHANGED) >= 1
    has_tick = bus.subscriber_count(Events.TICK_ADVANCED) >= 1
    check("G", "Event bus (§15): FIGHT_RESOLVED subscribers registered",
          has_fight, "")
    check("G", "Event bus (§15): TITLE_CHANGED subscriber registered",
          has_title, "")
    check("G", "Event bus (§15): TICK_ADVANCED subscriber registered",
          has_tick, "")
    conn.close()


# ----------------------------------------------------------------
# Bonus — TICK_ADVANCED → retirement news (smoke check)
# ----------------------------------------------------------------

def case_tick_retirement():
    """Verify generate_retirement_news fires on TICK_ADVANCED.

    Force a fighter to retirement-eligibility (age + low career_health),
    run a tick, and verify the news engine writes a retirement item.
    """
    print("\n--- Bonus: TICK_ADVANCED → retirement news ---")
    build_fresh_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    reset_bus()
    news.register_subscribers()
    # Force John Vale into retirement eligibility: age 45+ OR
    # (age 40+ AND career_health < 60). Vale was born 1994-05-11,
    # so by 2026-08-15 he's 32 — too young. Set his DOB back to
    # 1975 (makes him ~51) and career_health=30 to force retirement.
    conn.execute(
        "UPDATE fighters SET date_of_birth='1975-05-11' WHERE fighter_id=1"
    )
    conn.execute(
        "UPDATE fighter_career SET career_health=30, "
        "record_wins=18, record_losses=7, record_draws=1, "
        "title_reigns=2 WHERE fighter_id=1"
    )
    conn.commit()
    # Run a tick — _check_retirements will retire Vale and write
    # an inline 'retirement' topic news item; the TICK_ADVANCED
    # event then fires generate_retirement_news which polls for
    # the inline item and writes a rich news_engine retirement item.
    import tick_processor
    tick_processor.run_tick(conn, "day", 1)
    conn.commit()
    retired = conn.execute(
        "SELECT is_retired FROM fighters WHERE fighter_id=1"
    ).fetchone()
    check("X", "forced-eligible fighter actually retired",
          retired and retired[0] == 1, f"is_retired={retired}")
    ne_retirement = conn.execute(
        "SELECT headline FROM news_items WHERE topic='news_engine' "
        "AND fighter_id=1 AND (headline LIKE '%hangs them up%' "
        "OR headline LIKE '%retire%' OR headline LIKE '%walks away%' "
        "OR headline LIKE '%calls it a career%')"
    ).fetchall()
    check("X", "TICK_ADVANCED triggered news_engine retirement item",
          len(ne_retirement) >= 1, f"got={len(ne_retirement)}")
    if ne_retirement:
        print(f"      retirement headline: {ne_retirement[0][0]}")
        # Verify no raw numbers in the retirement body (CONVENTIONS §14)
        body_row = conn.execute(
            "SELECT body FROM news_items WHERE topic='news_engine' "
            "AND fighter_id=1 AND (headline LIKE '%hangs them up%' "
            "OR headline LIKE '%retire%' OR headline LIKE '%walks away%' "
            "OR headline LIKE '%calls it a career%') LIMIT 1"
        ).fetchone()
        if body_row:
            body = body_row[0]
            has_digit = bool(_DIGIT_RE.search(body))
            check("X", "retirement body has no raw numbers (§14)",
                  not has_digit,
                  f"body={body[:80]!r}..." if has_digit else "")
            print(f"      retirement body: {body}")
    conn.close()


def main():
    print("=" * 80)
    print(f"Task 23 — News Engine acceptance test "
          f"(schema {EXPECTED_VERSION}, no schema change)")
    print("=" * 80)
    case_a_imports()
    case_b_variety()
    case_c_no_raw_numbers()
    case_d_fight_resolved_triggers()
    case_e_title_changed_triggers()
    case_f_voice_descriptors()
    case_g_design_law()
    case_tick_retirement()
    print("\n" + "=" * 80)
    n_pass = sum(1 for r in results if r[2])
    n_fail = sum(1 for r in results if not r[2])
    print(f"Total: {n_pass} PASS, {n_fail} FAIL")
    print("=" * 80)
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
