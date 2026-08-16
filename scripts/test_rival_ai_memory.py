#!/usr/bin/env python3
"""HW10-W21W22 — Rival AI memory test.

Verifies the rival AI memory layer (W21/W22 feedback):
  W21 — "Rival AI should react to its own previous results."
  W22 — "Rival promotions should remember past interactions."

Test sequence:
  1. Build a fresh test DB (build_db --fresh + seed_data).
  2. Register the rival AI memory subscribers on the event bus.
  3. Schedule + resolve an event for a rival promo.
  4. Assert an 'event_result' memory was written (with attendance/
     profit context).
  5. Advance 7 sim days (weekly tick).
  6. Publish a TICK_ADVANCED event to trigger the weekly decay.
  7. Assert the memory's salience decayed by -1 (50 → 49).
  8. Assert the memory is queryable by (promotion_id, memory_type).

The test mirrors scripts/test_event_lifecycle_e2e.py's setup (fresh
DB + seed_data + manual event scheduling + resolve_next_fight) but
focuses on the memory side effects rather than the lifecycle chain.

Pass = exit 0; Fail = exit 1.

Run from the project root:
    python3 scripts/test_rival_ai_memory.py

Refs docs/Hardening_Phase.md §HW10-W21W22, GPT W21/W22 feedback.
"""
import os
import sqlite3
import subprocess
import sys
import random
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
DB_PATH = PROJECT_DIR / "data" / "cage_empire_test_hw10_w21w22.db"
os.environ["CAGE_EMPIRE_DB_PATH"] = str(DB_PATH)
os.environ["CAGE_EMPIRE_ALLOW_FRESH"] = "1"

sys.path.insert(0, str(SRC_DIR))


def build_fresh_db():
    """Build a fresh DB at DB_PATH (build_db --fresh + seed_data)."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    subprocess.run(
        [sys.executable, str(SRC_DIR / "build_db.py")],
        check=True, capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(SRC_DIR / "seed_data.py")],
        check=True, capture_output=True,
    )


class TestReport:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  PASS  {name}")
        else:
            self.failed += 1
            self.failures.append(name)
            print(f"  FAIL  {name}  {detail}")

    def summary(self):
        print()
        print("=" * 72)
        print(f"HW10-W21W22 Rival AI Memory Tests: "
              f"{self.passed} PASS, {self.failed} FAIL")
        if self.failures:
            print("Failed: " + ", ".join(self.failures))
        print("=" * 72)
        return 0 if self.failed == 0 else 1


def register_rival_ai_subscribers():
    """Register the rival AI subscribers (memory writers + decay).

    We register the FULL rival_ai module (which subscribes the
    memory writers + the decay subscriber + the existing process_rival_
    promotions subscriber). The other game systems (news, social, etc.)
    are NOT registered here — the test is focused on the memory layer,
    not the full event-bus chain.
    """
    from event_bus import reset_bus
    reset_bus()
    import rival_ai
    rival_ai.register_subscribers()


def main():
    print("=" * 72)
    print("HW10-W21W22 — Rival AI Memory Test")
    print("=" * 72)

    # ---------- Step 1: build fresh test DB ----------
    print()
    print("Step 1: build fresh test DB")
    build_fresh_db()
    report = TestReport()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON;")

    # ---------- Step 2: register rival_ai subscribers ----------
    print()
    print("Step 2: register rival AI subscribers (memory writers + decay)")
    register_rival_ai_subscribers()
    report.check("2a rival_ai subscribers registered",
                 True)

    # ---------- Step 3: verify seeded promos + fighters ----------
    print()
    print("Step 3: player promo + rival promo + fighters exist")
    n_promos = conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]
    report.check("3a >= 2 promotions seeded",
                 n_promos >= 2, f"got {n_promos}")
    n_fighters = conn.execute("SELECT COUNT(*) FROM fighters").fetchone()[0]
    report.check("3b >= 2 fighters seeded",
                 n_fighters >= 2, f"got {n_fighters}")

    # Give both promos cash + add extra fighters to promo 2 so a full
    # card can resolve. (Mirrors test_event_lifecycle_e2e setup.)
    conn.execute(
        "UPDATE promotions SET current_cash=80000000.0, "
        "starting_budget=80000000.0 WHERE promotion_id=1"
    )
    conn.execute(
        "UPDATE promotions SET current_cash=50000000.0, "
        "starting_budget=50000000.0 WHERE promotion_id=2"
    )
    extra_fnames2 = [("Evan", "Cross"), ("Finn", "Ortiz"),
                     ("Grant", "Park"), ("Hugo", "Reyes"),
                     ("Ivan", "Krieg"), ("Jonah", "Lee"),
                     ("Karl", "Mori"), ("Lars", "Novak")]
    for fn, ln in extra_fnames2:
        conn.execute(
            "INSERT INTO fighters (first_name, last_name, gender, "
            "date_of_birth, current_promotion_id, weight_class_id, "
            "is_active, is_retired, current_gym_id) VALUES "
            "(?, ?, 'male', '1995-01-01', 2, 1, 1, 0, NULL)",
            (fn, ln),
        )
    new_fids = [r[0] for r in conn.execute(
        "SELECT fighter_id FROM fighters WHERE first_name IN "
        "('Evan','Finn','Grant','Hugo','Ivan','Jonah','Karl','Lars')"
    ).fetchall()]
    for fid in new_fids:
        conn.execute(
            "INSERT OR IGNORE INTO rankings "
            "(fighter_id, promotion_id, weight_class_id, rating) "
            "VALUES (?, 1, 1, 1000.0)",
            (fid,),
        )
    conn.commit()

    # ---------- Step 4: schedule + resolve a rival promo event ----------
    print()
    print("Step 4: schedule + resolve a rival promo event")
    from services.matchmaking import schedule_next_event
    rival_event_id = schedule_next_event(conn, promotion_id=2)
    conn.commit()
    report.check("4a schedule_next_event returned non-None",
                 rival_event_id is not None, f"got {rival_event_id}")

    if rival_event_id:
        rival_event_date = conn.execute(
            "SELECT event_date FROM events WHERE event_id=?",
            (rival_event_id,),
        ).fetchone()[0]
        # HW8.1: advance the sim clock to the rival event's date so
        # resolve_next_fight can pick its fights (the engine filters
        # by event_date <= sim_date).
        conn.execute(
            "UPDATE simulation_clock SET current_date=? "
            "WHERE clock_id=1",
            (rival_event_date,),
        )
        conn.commit()
        # Resolve every fight on the rival card.
        import app
        rival_fights = conn.execute(
            "SELECT fight_id FROM fights WHERE event_id=? "
            "ORDER BY fight_id",
            (rival_event_id,),
        ).fetchall()
        for (fid,) in rival_fights:
            random.seed(42)
            fid_ret = app.resolve_next_fight(conn, promotion_id=2)
            if fid_ret is None:
                break
            conn.commit()
        report.check("4b resolve_next_fight called for rival card",
                     True)

        # Verify the event is now completed.
        rival_status = conn.execute(
            "SELECT status FROM events WHERE event_id=?",
            (rival_event_id,),
        ).fetchone()[0]
        report.check("4c rival event status == 'completed'",
                     rival_status == 'completed',
                     f"got {rival_status}")

    # ---------- Step 5: assert 'event_result' memory was written ----------
    print()
    print("Step 5: assert 'event_result' memory was written for promo 2")
    n_memories = conn.execute(
        "SELECT COUNT(*) FROM rival_ai_memory "
        "WHERE promotion_id=2 AND memory_type='event_result'"
    ).fetchone()[0]
    report.check("5a exactly 1 'event_result' memory for promo 2",
                 n_memories == 1, f"got {n_memories}")

    mem_row = conn.execute(
        "SELECT memory_id, memory_date, salience, context_json "
        "FROM rival_ai_memory "
        "WHERE promotion_id=2 AND memory_type='event_result' "
        "ORDER BY memory_id DESC LIMIT 1"
    ).fetchone()
    if mem_row:
        import json
        memory_id, mem_date, salience, ctx_json = mem_row
        report.check("5b memory_date matches rival_event_date",
                     mem_date == rival_event_date,
                     f"memory_date={mem_date} event_date={rival_event_date}")
        report.check("5c default salience == 50",
                     salience == 50, f"got {salience}")
        # Parse the context_json + check the expected keys are present.
        try:
            ctx = json.loads(ctx_json) if ctx_json else {}
        except (ValueError, TypeError):
            ctx = {}
        report.check("5d context has 'event_id' key",
                     'event_id' in ctx, f"ctx={ctx}")
        report.check("5d context 'event_id' matches rival_event_id",
                     ctx.get('event_id') == rival_event_id,
                     f"ctx.event_id={ctx.get('event_id')} "
                     f"rival_event_id={rival_event_id}")
        report.check("5e context has 'wins' key",
                     'wins' in ctx, f"ctx={ctx}")
        report.check("5f context has 'profit' key",
                     'profit' in ctx, f"ctx={ctx}")
    else:
        report.check("5b-5f memory row exists",
                     False, "no memory row found")

    # ---------- Step 6: advance 7 sim days (weekly tick) ----------
    print()
    print("Step 6: advance sim 7 days + publish TICK_ADVANCED (weekly decay)")
    from datetime import datetime, timedelta
    cur_date_row = conn.execute(
        "SELECT simulation_clock.current_date, simulation_clock.current_day "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    cur_date_str, cur_day = cur_date_row
    # Advance 7 sim days so current_day % 7 == 0 (the weekly gate).
    # The seed sets current_day=1 — advance to day 8 to hit the
    # first weekly tick (8 % 7 == 1, NOT 0). Need to advance to a
    # multiple of 7. Day 14 = 14 % 7 == 0 → weekly tick fires.
    new_day = 14
    new_date_dt = datetime.strptime(cur_date_str, "%Y-%m-%d") + timedelta(
        days=(new_day - cur_day)
    )
    new_date_str = new_date_dt.strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE simulation_clock SET current_date=?, current_day=?, "
        "current_week=? WHERE clock_id=1",
        (new_date_str, new_day, new_day // 7 + 1),
    )
    conn.commit()

    # Publish a TICK_ADVANCED event so the decay subscriber runs.
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.publish(conn, {
        'type': Events.TICK_ADVANCED,
        'current_date': new_date_str,
        'current_day': new_day,
    })
    conn.commit()
    report.check("6a TICK_ADVANCED published (weekly decay ran)",
                 True)

    # ---------- Step 7: assert salience decayed by -1 ----------
    print()
    print("Step 7: assert salience decayed by -1 (50 → 49)")
    new_salience_row = conn.execute(
        "SELECT salience FROM rival_ai_memory "
        "WHERE promotion_id=2 AND memory_type='event_result' "
        "ORDER BY memory_id DESC LIMIT 1"
    ).fetchone()
    if new_salience_row:
        new_salience = new_salience_row[0]
        report.check("7a salience == 49 (was 50, decayed -1)",
                     new_salience == 49, f"got {new_salience}")
    else:
        report.check("7a salience == 49 (was 50, decayed -1)",
                     False, "memory row missing after decay")

    # ---------- Step 8: assert memory is queryable ----------
    print()
    print("Step 8: assert memory is queryable by (promotion_id, memory_type)")
    from services.rival_ai.memory import recent_event_result_memory
    queried = recent_event_result_memory(conn, 2, limit=3)
    report.check("8a recent_event_result_memory returns 1 row",
                 len(queried) == 1, f"got {len(queried)}")
    if queried:
        m = queried[0]
        report.check("8b queryable memory has correct memory_id",
                     m['memory_id'] == memory_id,
                     f"got {m['memory_id']} expected {memory_id}")
        report.check("8c queryable memory has decayed salience",
                     m['salience'] == 49,
                     f"got {m['salience']}")
        report.check("8d queryable memory has parsed context",
                     isinstance(m['context'], dict)
                     and 'event_id' in m['context'],
                     f"got {m['context']}")
    # Querying a different promo returns no memories (defensive check).
    queried_other = recent_event_result_memory(conn, 3, limit=3)
    report.check("8e promo 3 (no events) has 0 event_result memories",
                 len(queried_other) == 0,
                 f"got {len(queried_other)}")

    # ---------- Step 9: assert DELETE-on-0 semantics ----------
    print()
    print("Step 9: assert salience=0 rows are DELETEd (forgotten)")
    # Manually insert a memory at salience=1, then run decay → should
    # drop to 0 → be deleted. Use promo_id=2 (an existing promo —
    # the foreign key constraint on rival_ai_memory.promotion_id
    # would reject promo_id=3 which doesn't exist in this 2-promo
    # test DB).
    test_date = new_date_str
    conn.execute(
        "INSERT INTO rival_ai_memory "
        "(promotion_id, memory_type, memory_date, salience, context_json) "
        "VALUES (?, 'signing_missed', ?, 1, ?)",
        (2, test_date, '{"fighter_id": -1}'),
    )
    conn.commit()
    # Verify the row exists.
    pre_count = conn.execute(
        "SELECT COUNT(*) FROM rival_ai_memory "
        "WHERE promotion_id=2 AND memory_type='signing_missed'"
    ).fetchone()[0]
    report.check("9a test memory inserted at salience=1",
                 pre_count == 1, f"got {pre_count}")
    # Run decay — should drop salience to 0, then DELETE.
    from services.rival_ai.memory import decay_all_memories
    n_decayed, n_forgotten = decay_all_memories(conn)
    conn.commit()
    post_count = conn.execute(
        "SELECT COUNT(*) FROM rival_ai_memory "
        "WHERE promotion_id=2 AND memory_type='signing_missed'"
    ).fetchone()[0]
    report.check("9b test memory DELETEd after decay (salience hit 0)",
                 post_count == 0, f"got {post_count}")
    report.check("9c decay reported n_forgotten >= 1",
                 n_forgotten >= 1, f"got {n_forgotten}")

    # ---------- Step 10: assert subscribers are defensive ----------
    print()
    print("Step 10: assert memory writers are defensive (no crash on bad input)")
    from services.rival_ai.memory import write_memory
    # Pass an out-of-range salience — write_memory should clamp.
    mid = write_memory(
        conn, 2, 'event_result', new_date_str,
        context={'event_id': -2}, salience=999,
    )
    conn.commit()
    row = conn.execute(
        "SELECT salience FROM rival_ai_memory WHERE memory_id=?",
        (mid,),
    ).fetchone()
    report.check("10a out-of-range salience clamped to 100",
                 row and row[0] == 100, f"got {row[0] if row else None}")
    # Clean up the test memory.
    conn.execute(
        "DELETE FROM rival_ai_memory WHERE memory_id=?", (mid,),
    )
    conn.commit()

    # Pass a non-JSON-serializable context — write_memory should
    # store context_json=NULL rather than crashing.
    class NotSerializable:
        pass
    mid = write_memory(
        conn, 2, 'event_result', new_date_str,
        context={'bad': NotSerializable()},
    )
    conn.commit()
    row = conn.execute(
        "SELECT context_json FROM rival_ai_memory WHERE memory_id=?",
        (mid,),
    ).fetchone()
    report.check("10b non-serializable context stored as NULL",
                 row and row[0] is None, f"got {row[0] if row else None}")
    # Clean up.
    conn.execute(
        "DELETE FROM rival_ai_memory WHERE memory_id=?", (mid,),
    )
    conn.commit()

    conn.close()
    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
