"""Run the simulation forward 30 in-game days to unfreeze the world.

This is the single highest-impact action from the REPLAN_RESET.md plan.
The world DB is frozen (sim clock at day 1, 0 news items, 0 scheduled
events, 15 stale momentum phrases). Running the sim forward will:
  - Populate news_items (so News section shows real stories)
  - Create scheduled events (so Next Event shows a real countdown)
  - Generate finance_transactions (so the cash sparkline trends)
  - Refresh daily_headlines (so Top Story rotates)
  - Trigger the ENGINE_VERSION mismatch → cache rebuild → 8-variant
    phrases (so Fighter Watch shows varied momentum)

Usage:
    cd /home/z/my-project/cage_empire
    python3 scripts/run_sim_forward.py [days]

Default: 30 days. Backs up the DB first.
"""
import sys
import os
import sqlite3
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    db_path = PROJECT_ROOT / "data" / "cage_empire.db"
    backup_path = PROJECT_ROOT / "data" / "cage_empire.db.bak.pre-sim-advance"

    # Backup (only if not already backed up)
    if not backup_path.exists():
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"  Backed up DB to {backup_path.name}")
    else:
        print(f"  Backup already exists: {backup_path.name}")

    print(f"  DB: {db_path}")
    print(f"  Advancing {days} days...")
    print()

    # Connect
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")

    # Check starting state
    clock_before = conn.execute(
        "SELECT current_date, current_day, current_month, current_year "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    news_before = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    events_scheduled_before = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status='scheduled'"
    ).fetchone()[0]
    headlines_before = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines"
    ).fetchone()[0]
    cache_meta = conn.execute(
        "SELECT engine_version, last_built_date FROM interpretation_cache_meta WHERE meta_id=1"
    ).fetchone()

    print(f"  BEFORE:")
    print(f"    Sim date: {clock_before[0]} (day {clock_before[1]})")
    print(f"    news_items: {news_before}")
    print(f"    scheduled events: {events_scheduled_before}")
    print(f"    daily_headlines: {headlines_before}")
    print(f"    cache engine_version: {cache_meta[0]}, last_built: {cache_meta[1]}")
    print()

    # Register all event-bus subscribers — mirrors app.py exactly.
    # REPLAN-B FIX: the prior version listed 16 modules but 8 were
    # misnamed (lived in src/services/ as services.training_svc, not
    # top-level training_svc) AND rival_ai was missing entirely. The
    # silent 'except ImportError: pass' swallowed all 9 failures, so
    # the 30-day advance ran with NONE of these services active. That's
    # why the world was dead (0 scheduled events, 0 signings, etc.).
    #
    # This version mirrors app.py's registration (lines 196-292) so the
    # bulk-advance produces the same world state the player would see.
    registered_count = 0
    failed_count = 0

    # Top-level modules (src/*.py — importable as bare name)
    top_level_modules = [
        "news", "social", "rivalries", "punditry", "morale",
        "suspensions", "agent_offers", "career_arc", "rival_ai",
        "show_rating", "venues", "save_load", "player_settings",
        "reputation", "scouting",
    ]
    for mod_name in top_level_modules:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
                registered_count += 1
        except ImportError:
            failed_count += 1
            print(f"  Warning: could not import {mod_name} (not found)")
        except Exception as e:
            failed_count += 1
            print(f"  Warning: {mod_name}.register_subscribers failed: {e}")

    # Service modules (src/services/*.py — must import as services.X)
    service_modules = [
        "services.hof_svc", "services.retirement_svc",
        "services.training_svc", "services.injuries_svc",
        "services.finance_svc", "services.rivalries_svc",
        "services.memory_svc", "services.contracts",
        "services.scouting_svc", "services.matchmaking",
        "services.punditry_svc",
        # v3.14.0 (Task RIVAL-AI-P1): pruning service — runs on the
        # 1st of each in-game month + DELETEs old news_items /
        # daily_headlines / social_posts / injuries / suspensions /
        # training_camps / scouting_reports. Keeps the DB lean over
        # multi-year sims. Registered here so the bulk-advance
        # produces the same world state the player would see.
        "services.pruning_svc",
    ]
    for mod_name in service_modules:
        try:
            mod = __import__(mod_name, fromlist=["register_subscribers"])
            if hasattr(mod, "register_subscribers"):
                mod.register_subscribers()
                registered_count += 1
        except ImportError:
            failed_count += 1
            print(f"  Warning: could not import {mod_name} (not found)")
        except Exception as e:
            failed_count += 1
            print(f"  Warning: {mod_name}.register_subscribers failed: {e}")

    # Interpretation layer (the daily pass that rebuilds fighter_descriptors)
    try:
        from interpretation import register_subscribers as _register_interp
        _register_interp()
        registered_count += 1
    except ImportError:
        failed_count += 1
        print(f"  Warning: could not import interpretation")
    except Exception as e:
        failed_count += 1
        print(f"  Warning: interpretation.register_subscribers failed: {e}")

    print(f"  Registered {registered_count} event-bus subscribers "
          f"({failed_count} failed)")

    # Import advance_day
    from services.clock import advance_day

    # Advance day × days
    t0 = time.perf_counter()
    success_count = 0
    fail_count = 0
    for i in range(days):
        try:
            advance_day(conn)
            conn.commit()
            success_count += 1
            if (i + 1) % 5 == 0:
                # Progress update every 5 days
                clock = conn.execute(
                    "SELECT current_date FROM simulation_clock WHERE clock_id=1"
                ).fetchone()
                print(f"    Day {i+1}/{days}: {clock[0]}")
        except Exception as e:
            fail_count += 1
            if fail_count <= 3:
                print(f"    Day {i+1} FAILED: {e}")
            conn.rollback()
            # Try to continue — don't let one bad day stop the whole run

    t1 = time.perf_counter()
    elapsed = t1 - t0

    # Check ending state
    clock_after = conn.execute(
        "SELECT current_date, current_day, current_month, current_year "
        "FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    news_after = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    events_scheduled_after = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status='scheduled'"
    ).fetchone()[0]
    events_completed_after = conn.execute(
        "SELECT COUNT(*) FROM events WHERE status='completed'"
    ).fetchone()[0]
    headlines_after = conn.execute(
        "SELECT COUNT(*) FROM daily_headlines"
    ).fetchone()[0]
    cache_meta_after = conn.execute(
        "SELECT engine_version, last_built_date, last_built_fighter_count "
        "FROM interpretation_cache_meta WHERE meta_id=1"
    ).fetchone()
    # Distinct momentum phrases
    distinct_phrases = conn.execute(
        "SELECT COUNT(DISTINCT SUBSTR(momentum, INSTR(momentum, '||')+2)) "
        "FROM fighter_descriptors WHERE momentum IS NOT NULL"
    ).fetchone()[0]
    # Finance transactions
    fin_count = conn.execute(
        "SELECT COUNT(*) FROM finance_transactions"
    ).fetchone()[0]
    # Fight history
    fh_count = conn.execute(
        "SELECT COUNT(*) FROM fight_history"
    ).fetchone()[0]

    print()
    print(f"  AFTER ({success_count} days advanced, {fail_count} failed, {elapsed:.1f}s):")
    print(f"    Sim date: {clock_after[0]} (day {clock_after[1]})")
    print(f"    news_items: {news_before} → {news_after}")
    print(f"    scheduled events: {events_scheduled_before} → {events_scheduled_after}")
    print(f"    completed events: → {events_completed_after}")
    print(f"    daily_headlines: {headlines_before} → {headlines_after}")
    print(f"    finance_transactions: → {fin_count}")
    print(f"    fight_history: → {fh_count}")
    print(f"    cache engine_version: {cache_meta_after[0]}, last_built: {cache_meta_after[1]}")
    print(f"    distinct momentum phrases: 15 → {distinct_phrases}")

    print()
    if news_after > 0 and events_scheduled_after > 0 and distinct_phrases > 20:
        print("  ✓ WORLD IS ALIVE — Dashboard should now show real data.")
    else:
        print("  ⚠ Partial — some data may still be missing. Check the numbers above.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
