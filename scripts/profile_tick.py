#!/usr/bin/env python3
"""Profile a single tick to identify the actual perf bottleneck.

Runs ONE advance_day + interpretation pass on the live world DB,
instrumented with cProfile. Prints the top 30 cumulative-time
functions.
"""
import cProfile
import pstats
import sqlite3
import sys
import time
from io import StringIO
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

# Backup the DB before profiling (so we don't advance the live clock).
import shutil
src_db = PROJECT_DIR / "data" / "cage_empire.db"
prof_db = PROJECT_DIR / "data" / "cage_empire_prof.db"
shutil.copy2(str(src_db), str(prof_db))

# Set the env var so all modules pick up the profiling DB.
import os
os.environ["CAGE_EMPIRE_DB_PATH"] = str(prof_db)

# Import the modules we're profiling.
from services.clock import advance_day
from tick_processor import _run_one_tick_body, _record_tick_health
from event_bus import get_bus, reset_bus
from interpretation.snapshot_cache import run_daily_interpretation_pass

# Register subscribers (so the tick actually does work).
# Use the same list as app_web.py's _register_event_subscribers.
registration_modules = [
    "news", "social", "rivalries", "punditry", "morale",
    "suspensions", "agent_offers", "career_arc", "rival_ai",
    "show_rating", "finance", "venues", "save_load",
    "player_settings", "reputation",
]
for mod_name in registration_modules:
    try:
        mod = __import__(mod_name)
        if hasattr(mod, "register_subscribers"):
            mod.register_subscribers()
    except Exception as e:
        print(f"WARN: {mod_name}.register_subscribers failed: {e}", flush=True)

# services.* subscribers.
for svc_name in ("hof_svc", "pruning_svc", "memory_svc", "punditry_svc", "rivalries_svc"):
    try:
        mod = __import__(f"services.{svc_name}", fromlist=[svc_name])
        if hasattr(mod, "register_subscribers"):
            mod.register_subscribers()
    except Exception as e:
        print(f"WARN: services.{svc_name}.register_subscribers failed: {e}", flush=True)

# Interpretation layer.
try:
    from interpretation import register_subscribers as _reg_interp
    _reg_interp()
except Exception as e:
    print(f"WARN: interpretation.register_subscribers failed: {e}", flush=True)

# Also wire rival_ai (it registers itself on first call to run_tick).
import rival_ai

# Open the DB + profile a single tick.
conn = sqlite3.connect(str(prof_db))
conn.execute("PRAGMA foreign_keys = ON;")

# Warm up (so first-call imports don't dominate).
import time as _t
_t.sleep(0.1)

# Profile.
pr = cProfile.Profile()
pr.enable()

t0 = time.perf_counter()
# Run the tick body (advances clock + all daily work + publishes TICK_ADVANCED).
import datetime as _dt
try:
    new_date = _run_one_tick_body(conn, tick_type="day")
    conn.commit()
    t_body = time.perf_counter() - t0
    print(f"Tick body (clock advance + daily sim + commit): {t_body*1000:.1f}ms")
    print(f"  new sim date: {new_date}")
except Exception as e:
    print(f"Tick body FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Profile the interpretation pass separately.
t1 = time.perf_counter()
try:
    run_daily_interpretation_pass(conn)
    t_interp = time.perf_counter() - t1
    print(f"Interpretation pass (snapshot_cache): {t_interp*1000:.1f}ms")
except Exception as e:
    print(f"Interpretation pass FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

pr.disable()

# Print the top 30 cumulative-time functions.
s = StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(30)
print()
print("=" * 80)
print("TOP 30 FUNCTIONS BY CUMULATIVE TIME")
print("=" * 80)
print(s.getvalue())

# Cleanup.
conn.close()
prof_db.unlink()  # delete the profiling DB
