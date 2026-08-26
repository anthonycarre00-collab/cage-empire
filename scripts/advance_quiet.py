#!/usr/bin/env python3
"""Phase 8 — Quiet resumable day-advancer for long soaks.

Advances the sim toward a target tick, ONE quiet chunk at a time.
- Prints only ONE line per 100 days (so output stays tiny).
- Commits after each day (resumable — survives interruption).
- Registers the lightweight event-bus subscribers (mirrors soak_test.py,
  avoids importing app_web which would boot the full web app).

Usage:
    python3 scripts/advance_quiet.py --target-day 1825 --max-seconds 540
    python3 scripts/advance_quiet.py --days 200 --max-seconds 540
"""
import argparse, sqlite3, sys, time, os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


def register_subscribers():
    """Lightweight subscriber registration (mirrors soak_test.py)."""
    top_level = [
        "news", "social", "rivalries", "punditry", "morale",
        "suspensions", "agent_offers", "career_arc", "rival_ai",
        "show_rating", "venues", "save_load", "player_settings",
        "reputation", "scouting", "gym_transfers",
    ]
    for mod_name in top_level:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
        except Exception:
            pass
    services = [
        "services.hof_svc", "services.retirement_svc",
        "services.training_svc", "services.injuries_svc",
        "services.finance_svc", "services.rivalries_svc",
        "services.memory_svc", "services.contracts",
        "services.scouting_svc", "services.matchmaking",
        "services.punditry_svc", "services.pruning_svc",
    ]
    for mod_name in services:
        try:
            mod = __import__(mod_name, fromlist=["register_subscribers"])
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
        except Exception:
            pass
    # Suppress the verbose per-day training-camp / retirement print spam
    # by silencing stdout during tick processing would break the checkpoint
    # prints — instead, redirect tick_processor + helper module loggers.
    import io
    # Replace print globally with a no-op for the duration of the run
    # (we use our own checkpoint prints only).
    # NOTE: this is aggressive but effective — the soak script's own
    # per-day prints are what's blowing up the log file.
    global _original_print
    _original_print = print
    builtins_print = __builtins__["print"] if isinstance(__builtins__, dict) else __builtins__.print
    if isinstance(__builtins__, dict):
        __builtins__["print"] = lambda *a, **k: None
    else:
        __builtins__.print = lambda *a, **k: None


def restore_print():
    """Restore print for our own checkpoint output."""
    if isinstance(__builtins__, dict):
        __builtins__["print"] = _original_print
    else:
        __builtins__.print = _original_print


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target-day", type=int)
    p.add_argument("--days", type=int)
    p.add_argument("--max-seconds", type=int, default=540)
    args = p.parse_args()

    from tick_processor import run_tick

    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL;")
    db.execute("PRAGMA busy_timeout=30000;")

    register_subscribers()

    cur = db.cursor()
    r = cur.execute("SELECT current_date, tick_counter FROM simulation_clock").fetchone()
    start_tick = r[1]
    start_date = r[0]

    if args.target_day:
        target_tick = args.target_day
    elif args.days:
        target_tick = start_tick + args.days
    else:
        print("Must specify --target-day or --days", file=sys.stderr)
        return 1

    days_to_go = target_tick - start_tick
    if days_to_go <= 0:
        print(f"Already at tick {start_tick} (target {target_tick}) — nothing to do")
        return 0

    print(f"ADVANCE: tick {start_tick} ({start_date}) → {target_tick} ({days_to_go} days)",
          flush=True)
    t0 = time.time()
    errors = 0

    for i in range(days_to_go):
        try:
            run_tick(db)
            db.commit()
        except Exception as e:
            errors += 1
            print(f"  ERROR tick {start_tick + i}: {e}", flush=True)
            db.rollback()
            if errors > 20:
                print("Too many errors, stopping", flush=True)
                break

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            done = i + 1
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (days_to_go - done) / rate if rate > 0 else 0
            r = cur.execute(
                "SELECT current_date, tick_counter FROM simulation_clock"
            ).fetchone()
            print(f"  [{done}/{days_to_go}] tick={r[1]} sim={r[0]} | "
                  f"{rate:.1f}d/s | ~{remaining:.0f}s left | {errors} err",
                  flush=True)

        if time.time() - t0 > args.max_seconds:
            r = cur.execute("SELECT tick_counter FROM simulation_clock").fetchone()
            print(f"  Max sec reached at tick {r[1]} (target {target_tick})",
                  flush=True)
            break

    elapsed = time.time() - t0
    r = cur.execute("SELECT current_date, tick_counter FROM simulation_clock").fetchone()
    print(f"DONE: tick {start_tick} → {r[1]} ({r[0]}) in {elapsed:.0f}s, {errors} errors",
          flush=True)

    # Health snapshot
    promos = cur.execute(
        "SELECT size_tier, COUNT(*) as n, "
        "SUM(CASE WHEN financial_state='HEALTHY' THEN 1 ELSE 0 END) as healthy, "
        "SUM(CASE WHEN financial_state='REBUILDING' THEN 1 ELSE 0 END) as rebuild, "
        "MIN(current_cash) as min_cash, MAX(current_cash) as max_cash "
        "FROM promotions GROUP BY size_tier ORDER BY size_tier"
    ).fetchall()
    print("\n=== Promo health ===")
    for p in promos:
        print(f"  {p['size_tier']:6s}: {p['healthy']}/{p['n']} HEALTHY, "
              f"{p['rebuild']} REBUILD | ${p['min_cash']:,.0f} – ${p['max_cash']:,.0f}")

    hof = cur.execute("SELECT COUNT(*) FROM hall_of_fame").fetchone()[0]
    mem = cur.execute("SELECT COUNT(*) FROM fighter_memory_links").fetchone()[0]
    mr = cur.execute(
        "SELECT COUNT(*) FROM news_items WHERE topic='memory_resurfacing'"
    ).fetchone()[0]
    fin = cur.execute("SELECT COUNT(*) FROM finance_transactions").fetchone()[0]
    print(f"\nHoF: {hof} | mem_links: {mem} | mem_resurf_news: {mr} | fin_txn: {fin}")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
