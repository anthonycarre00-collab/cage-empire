#!/usr/bin/env python3
"""HW1.1 (Hardening Phase §HW1.1) — Verify the finance registration chain.

Verifies that:
  1. `src/app_web.py::register_all_subscribers()` includes `"finance"`
     in its `registration_modules` list (production entry point).
  2. `finance.register_subscribers()` actually subscribes a callback
     to `Events.EVENT_COMPLETED` on the event bus.
  3. A 7-day forward sim with ALL subscribers registered (mirroring
     the app's registration order exactly) writes new
     `finance_transactions` rows for every newly-completed event.

The script makes a temp copy of the live DB and runs the sim against
the copy — the production DB is NEVER mutated. Pass = exit 0; Fail =
exit 1.

Run from the project root:
    python3 scripts/verify_finance_chain.py

Background (Hardening_Phase.md §HW1.1 / CRITICAL #1):
  The original audit (docs/Hardening_Phase.md §1) flagged that
  `finance.register_subscribers()` "exists but may not be called in
  the production entry point". The fix landed in Phase E1.1
  (`finance` added to app_web.py's `registration_modules` list).

  This script is the regression guard — it asserts the chain is
  intact end-to-end. If a future refactor drops `finance` from the
  list or breaks the bus subscription, this script fails immediately.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


# ------------------------------------------------------------ read source code
def _registration_modules_from_source():
    """Read app_web.py and extract the registration_modules list literal.

    Returns the list of module-name strings. Raises if the list can't
    be located (defensive — keeps the test honest if app_web.py's
    structure changes substantially).
    """
    src = (SRC_DIR / "app_web.py").read_text()
    needle = "registration_modules = ["
    i = src.find(needle)
    if i < 0:
        raise AssertionError("Could not find registration_modules list in app_web.py")
    j = src.find("]", i)
    if j < 0:
        raise AssertionError("Could not find end of registration_modules list")
    block = src[i + len(needle):j]
    # Pull every quoted string out of the block.
    import re
    return re.findall(r'"([a-zA-Z0-9_\.]+)"', block)


# ------------------------------------------------------------ tests
def test_finance_in_registration_modules():
    """HW1.1 step 1: `finance` is in app_web.py registration_modules."""
    mods = _registration_modules_from_source()
    assert "finance" in mods, (
        f"'finance' missing from app_web.py registration_modules. "
        f"Found: {mods}"
    )
    print(f"  step 1 PASS: 'finance' in registration_modules (list has {len(mods)} entries)")


def test_finance_subscribes_to_event_completed():
    """HW1.1 step 2: finance.register_subscribers wires a callback to
    Events.EVENT_COMPLETED on the event bus."""
    # Reset the bus so we get a deterministic subscriber count.
    from event_bus import get_bus, reset_bus, Events
    reset_bus()
    import finance
    finance.register_subscribers()
    bus = get_bus()
    subs = bus._subscribers.get(Events.EVENT_COMPLETED, [])
    names = [name for (name, _fn) in subs]
    assert any("finance" in n for n in names), (
        f"No finance subscriber on EVENT_COMPLETED. Found: {names}"
    )
    print(f"  step 2 PASS: finance subscribes to EVENT_COMPLETED "
          f"(subs: {names})")


def test_7day_sim_writes_finance_transactions():
    """HW1.1 step 3: a 7-day sim writes finance_transactions for
    newly-completed events.

    Strategy: copy the live DB to a temp file, register every
    subscriber app_web.py would register (same order, same set), then
    advance 7 days. Assert:
      - At least 1 newly-completed event exists in the sim window.
      - Every newly-completed event has >= 1 finance_transactions row.
      - Every newly-completed event has >= 1 show_ratings row.
      - Every newly-completed event has >= 1 news_items row.
    """
    live_db = PROJECT_DIR / "data" / "cage_empire.db"
    if not live_db.exists():
        raise AssertionError(
            f"Live DB not found at {live_db}. Run ./run.sh build-world first."
        )
    # Temp copy — never mutate the production DB.
    tmp_dir = Path(tempfile.mkdtemp(prefix="hw1_finance_"))
    tmp_db = tmp_dir / "test.db"
    shutil.copy2(live_db, tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("PRAGMA foreign_keys = ON;")

    clock_before = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    ft_before = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions"
    ).fetchone()[0]
    sr_before = conn.execute("SELECT COUNT(*) FROM show_ratings").fetchone()[0]
    news_before = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    completed_before = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status='completed'"
    ).fetchone()[0]

    # Register every subscriber app_web.py would register, in the
    # same order. Mirrors src/app_web.py::register_all_subscribers.
    registration_modules = _registration_modules_from_source()
    for mod_name in registration_modules:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
        except Exception as e:
            print(f"  WARN: {mod_name}.register_subscribers failed: {e}")
    # Service-level subscribers (mirrors app_web.py).
    for sm in ("services.hof_svc", "services.pruning_svc"):
        try:
            mod = __import__(sm, fromlist=["register_subscribers"])
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
        except Exception as e:
            print(f"  WARN: {sm}: {e}")
    # Interpretation layer — registered LAST per CONVENTIONS §17.5.
    try:
        from interpretation import register_subscribers as _reg_interp
        _reg_interp()
    except Exception as e:
        print(f"  WARN: interpretation: {e}")

    # Advance 7 days.
    from services.clock import advance_day
    for i in range(7):
        try:
            advance_day(conn)
            conn.commit()
        except Exception as e:
            print(f"  WARN: advance_day {i+1}/7 failed: {e}")
            conn.rollback()

    # Assertions.
    clock_after = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()[0]
    completed_after = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status='completed'"
    ).fetchone()[0]
    ft_after = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions"
    ).fetchone()[0]
    sr_after = conn.execute("SELECT COUNT(*) FROM show_ratings").fetchone()[0]
    news_after = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]

    print(f"  step 3 sim: clock {clock_before} -> {clock_after}, "
          f"completed events {completed_before} -> {completed_after}, "
          f"finance_rows {ft_before} -> {ft_after}, "
          f"show_ratings {sr_before} -> {sr_after}, "
          f"news {news_before} -> {news_after}")

    newly_completed = conn.execute(
        "SELECT event_id, promotion_id, event_date, "
        "  (SELECT COUNT(*) FROM finance_transactions ft WHERE ft.event_id=e.event_id), "
        "  (SELECT COUNT(*) FROM show_ratings sr WHERE sr.event_id=e.event_id), "
        "  (SELECT COUNT(*) FROM news_items n WHERE n.event_id=e.event_id) "
        "FROM events e WHERE e.status='completed' "
        f"AND e.event_date > '{clock_before}' "
        "ORDER BY e.event_date"
    ).fetchall()
    assert len(newly_completed) >= 1, (
        "7-day sim produced 0 newly-completed events — sim environment "
        "may be stale (no scheduled events in window)."
    )
    print(f"  step 3 newly-completed events: {len(newly_completed)}")
    no_ft = []
    no_sr = []
    no_news = []
    for eid, pid, edate, ft_n, sr_n, news_n in newly_completed:
        if ft_n == 0:
            no_ft.append((eid, pid, edate))
        if sr_n == 0:
            no_sr.append((eid, pid, edate))
        if news_n == 0:
            no_news.append((eid, pid, edate))
    assert not no_ft, (
        f"{len(no_ft)} newly-completed events have 0 finance_transactions: "
        f"{no_ft[:5]}"
    )
    assert not no_sr, (
        f"{len(no_sr)} newly-completed events have 0 show_ratings: "
        f"{no_sr[:5]}"
    )
    assert not no_news, (
        f"{len(no_news)} newly-completed events have 0 news_items: "
        f"{no_news[:5]}"
    )
    print(f"  step 3 PASS: every newly-completed event has finance + "
          f"show_rating + news rows")
    conn.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    print("=" * 72)
    print("HW1.1 — Finance Registration Chain Verification")
    print("=" * 72)
    failures = 0
    for fn in (
        test_finance_in_registration_modules,
        test_finance_subscribes_to_event_completed,
        test_7day_sim_writes_finance_transactions,
    ):
        try:
            print(f"\n[{fn.__name__}]")
            fn()
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failures += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failures += 1
    print()
    print("=" * 72)
    if failures == 0:
        print("HW1.1 — PASS: finance registration chain is intact end-to-end.")
        print("  - 'finance' is in app_web.py registration_modules list")
        print("  - finance.register_subscribers subscribes to EVENT_COMPLETED")
        print("  - 7-day sim writes finance_transactions for every new event")
        return 0
    else:
        print(f"HW1.1 — FAIL: {failures} step(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
