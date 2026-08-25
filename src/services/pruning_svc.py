"""CAGE EMPIRE Pruning Service (Task ID RIVAL-AI-P1, Phase 1 — REPLAN_RESET §10).

A TICK_ADVANCED subscriber that runs on the 1st of each in-game month
and prunes old rows from 7 high-churn tables to keep the DB lean.
Without this, news_items / social_posts / daily_headlines /
injuries / suspensions / training_camps / scouting_reports grow
without bound — over a multi-year sim, the DB would balloon past
SQLite's practical limit and the UI's "recent news" queries would
slow to a crawl.

Pruning policy (TIER1-365DAY retuned 2027-02 — the original 365/90/180
thresholds were too conservative for 5-10 year soaks; per-tick cost
grew past day ~200 because the high-churn tables kept more rows than
the UI's "recent news" queries needed):
    news_items        > 180 days  (published_at)        [was 365]
    daily_headlines   >  60 days  (headline_date)        [was  90]
    social_posts      >  90 days  (post_date)            [was 180]
    injuries          > 180 days  (resolved only — is_active=0,
                                   pruned by actual_return_date or
                                   start_date fallback)  [was 365]
    suspensions       > 180 days  (expired only — is_active=0,
                                   pruned by end_date)   [was 365]
    training_camps    >  60 days  (completed only — is_completed=1,
                                   pruned by end_date)   [was  90]
    scouting_reports  >  90 days  (report_date)          [was 180]
    fight_beats       >   1 day   (created_at — NEW; pruned DAILY
                                   via a JOIN on fights.event_id →
                                   events WHERE status='completed'
                                   AND event_date < sim_date - 1 day)

All prunes are BATCHED (DELETE ... LIMIT 1000) so a single prune
tick doesn't lock the DB for seconds if a table has 100K+ rows. If
a batch fills, the next month's tick prunes the next 1000. This
bounds the monthly prune cost to < 500ms even on huge DBs.

fight_beats is the FASTEST-GROWING table (57K rows on a 30-day soak;
extrapolates to ~286K on a 5-year run). It's ONLY needed during fight
resolution + show_rating + morale + Fight Night UI display — all of
which happen on the event day. After the event completes, fight_beats
is NEVER read again. The DAILY prune (every tick, not just monthly)
keeps the table bounded to ~1 day of beats (~2K rows typical).

ENTIRELY EVENT-BUS-DRIVEN (CONVENTIONS §15.4 — no new inline side
effects added to run_tick). Subscribes to TICK_ADVANCED. Checks the
current sim date; if it's the 1st of the month, runs the prune.
Otherwise no-op (cheap SELECT on simulation_clock — < 1ms).

The prune itself prints a one-line summary so the operator can see
the DB staying lean:
    [pruning] Pruned 12 news_items, 8 daily_headlines, 3 social_posts,
              1 injuries, 0 suspensions, 5 training_camps, 0 scouting_reports

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it only DELETEs from existing tables (news_items,
        daily_headlines, social_posts, injuries, suspensions,
        training_camps, scouting_reports — all added by prior tasks).
  §13 — Design Law: Empire Builder pillar — keeping the DB lean is
        how the player's empire stays performant over multi-year
        sims. A slow DB would kill the Empire Builder fantasy.
  §14 — Voice Layer: N/A — pruning is internal housekeeping, no
        player-facing text.
  §15 — Event Bus: subscribes to TICK_ADVANCED. Defensive — any
        prune failure is caught + logged, never crashes the bus.
  §16 — Migration: NONE (no schema change — pruning is data-only).

USAGE:
    from services.pruning_svc import register_subscribers
    register_subscribers()  # call once at startup (App.__init__,
                            # run_sim_forward.py). Safe to call
                            # multiple times.
"""

import sqlite3
import sys


# ----------------------------------------------------------------
# Prune policy — (table_name, date_column, max_age_days, extra_where)
#
# `extra_where` is the optional filter that restricts the prune to
# "safe to delete" rows (e.g. only resolved injuries, only completed
# camps). Without it, the prune would delete ACTIVE injuries /
# suspensions / camps that happen to be old — breaking the sim.
#
# The DELETE uses SQLite's date() function for the age comparison:
#    date(current_date, '-N days') > date(table.date_column)
# This handles the 'YYYY-MM-DD' format used by all sim date columns.
# ----------------------------------------------------------------

_PRUNE_POLICY = (
    # (table,             date_column,           max_age_days, extra_where)
    # TIER1-365DAY — retuned 2027-02. Thresholds halved across the
    # board so the high-churn tables stay smaller over multi-year
    # runs (the original 365/90/180 values let news_items / social_
    # posts / injuries / suspensions grow to 50K+ rows by year 2,
    # slowing every "recent news" query).
    ("news_items",        "published_at",         180,
     "topic NOT IN ('awards', 'rival_recap', 'gym_transfer')"),
    ("daily_headlines",   "headline_date",         60, None),
    ("social_posts",      "post_date",             90, None),
    # Only prune RESOLVED injuries (is_active=0). Active injuries
    # are kept regardless of age — a fighter with a long-term injury
    # is still injured; pruning the row would un-injure them.
    ("injuries",          "COALESCE(actual_return_date, start_date)", 180,
     "is_active = 0"),
    # Only prune EXPIRED suspensions (is_active=0). Active
    # suspensions are kept until they expire naturally.
    ("suspensions",       "end_date",             180, "is_active = 0"),
    # Only prune COMPLETED training camps (is_completed=1). Active
    # camps (a fighter mid-camp for an upcoming fight) are kept.
    ("training_camps",    "end_date",              60, "is_completed = 1"),
    ("scouting_reports",  "report_date",           90, None),
    # fight_beats — NEW. Pruned DAILY (not monthly) via the special
    # case in _on_tick_advanced + _prune_fight_beats. Listed here
    # for documentation; the monthly _prune_table loop ALSO runs the
    # JOIN-based prune so a missed daily tick is caught by the
    # monthly sweep (the JOIN supersedes the date_column / extra_
    # where fields for this row — see _run_monthly_prune).
    ("fight_beats",       "created_at",             1, None),
    # ----------------------------------------------------------------
    # PERF-FIXES-3 — per-fight tables that grow unboundedly over
    # multi-year soaks. The audit (PERF_ARCH_AUDIT.md §2.2) found
    # `commentary_segments` was growing at ~80 rows per fight (36-140
    # 'beat' rows + 3-14 'highlight' rows + 5-20 'announcer'/'pundit'
    # /'crowd' rows). At 10 years the table hits 500K+ rows, slowing
    # every per-fight query (Fight Night UI, Fighter Profile replay,
    # show_rating FOTN award scan). Same problem on weight_cut_log,
    # fight_rounds, matchup_analyses, show_ratings, finance_
    # transactions, simulation_tick_health.
    #
    # All these are MONTHLY-pruned (run from _run_monthly_prune).
    # The fight_beats entry above is the only DAILY-pruned row.
    # ----------------------------------------------------------------
    # commentary_segments — the per-fight commentary feed (highlights
    # + per-beat play-by-play + announcer/pundit/crowd interjections).
    # The fight result + key moment summary live forever in news_items
    # + fight_history. Old commentary segments are only read by the
    # Fighter Profile "Replay fight" deep-link (player's own fighters
    # only — old rival-fight replays are NEVER browsed). 365 days
    # keeps a full year of replayable fights; older fights show a
    # "Replay not available" placeholder (acceptable UX per audit).
    ("commentary_segments", "created_at",          365, None),
    # weight_cut_log — per-fighter per-fight weight cut details (2
    # rows per fight). Only relevant for the fighter's NEXT fight
    # (the camp uses the last cut to calibrate). 365 days keeps the
    # recent cuts; old cuts are meaningless (the fighter's body has
    # changed, the weight class may have changed).
    ("weight_cut_log",      "created_at",          365, None),
    # fight_rounds — per-round aggregates (3-5 rows per fight). The
    # fight result is in `fights`; the round-by-round detail is only
    # read by the Fight Night UI (player's own fights only). 365 days
    # keeps recent fights replayable.
    ("fight_rounds",        "created_at",          365, None),
    # matchup_analyses — pre-fight pundit predictions (1 row per
    # scheduled fight). The "pundit take" is only useful BEFORE the
    # fight. After the fight, the result is in `fights` + news_items.
    # 365 days keeps recent predictions for the UI event page.
    ("matchup_analyses",    "created_at",          365, None),
    # show_ratings — per-event show ratings. Kept longer (730 days =
    # 2 years) for historical comparisons (year-over-year promotion
    # trend, Hof "best shows" lists). Older ratings are summarised
    # in the promotion's reputation column (a single int).
    ("show_ratings",        "created_at",          730, None),
    # finance_transactions — per-event finance ledger entries.
    # Kept 730 days (2 years) for W29 economic reconciliation
    # (year-over-year profit/loss, promotion cash trajectory).
    # Older transactions are summarised in promotions.cash_balance
    # + fighter_career.career_earnings (denormalized at write time).
    ("finance_transactions", "transaction_date",   730, None),
    # simulation_tick_health — per-tick health check log (errors +
    # warnings from the tick processor). Useful for diagnosing
    # recent issues; old tick health is irrelevant. 365 days keeps
    # a full year of history for post-mortem analysis.
    ("simulation_tick_health", "tick_date",        365, None),
    # ----------------------------------------------------------------
    # NEWS-FINANCE-GYM-LEGACY Issue 6.5 — long-lived news topics.
    #
    # The new news topics added by Issue 6.3 (year-end awards),
    # Issue 6.4 (rival event recaps), and Issue 8 (gym transfers)
    # are "year-in-review" content the player may browse up to a
    # year later. They're excluded from the 180-day news_items
    # prune above (via the extra_where clause) and pruned at 365
    # days via the entries below.
    #
    # Volume estimate: ~6 awards + ~150 rival recaps + ~15 gym
    # transfers = ~170 rows/year. At 365-day retention the steady-
    # state size is ~170 rows (acceptable — the table can hold
    # millions).
    # ----------------------------------------------------------------
    # awards — 6 LEGENDARY news items per Jan 1.
    ("news_items",        "published_at",         365,
     "topic = 'awards'"),
    # rival_recap — SIGNIFICANT news item per rival EVENT_COMPLETED.
    ("news_items",        "published_at",         365,
     "topic = 'rival_recap'"),
    # gym_transfer — ROUTINE news item per fighter gym change.
    ("news_items",        "published_at",         365,
     "topic = 'gym_transfer'"),
    # ----------------------------------------------------------------
    # PHASE8-B — fighter_memory_links unbounded growth fix.
    #
    # Phase 7 5-year soak showed this table grew 762 → 20,091 rows
    # (+19,329 over 5y, ~3,866/year). At this rate a 20y soak would
    # reach ~77K rows. Memory links are valuable for narrative ("this
    # fighter is the successor to a former champion"), so we DON'T
    # prune them too aggressively — only prune links older than 365
    # days where BOTH fighters are retired (the link is no longer
    # relevant to active gameplay). Active fighters' links are always
    # kept regardless of age (they may surface in future memory
    # resurfacing per src/interpretation/memory_engine.py).
    # ----------------------------------------------------------------
    ("fighter_memory_links", "created_at",          365,
     "linked_fighter_id IN (SELECT fighter_id FROM fighters "
     "WHERE is_retired=1) "
     "AND fighter_id IN (SELECT fighter_id FROM fighters "
     "WHERE is_retired=1)"),
)


# Batch size — limits each DELETE to 1000 rows so a single prune
# tick doesn't lock the DB for seconds on huge tables. If a table
# has 100K+ eligible rows, the prune runs in 1000-row chunks across
# multiple months (each chunk takes < 50ms).
_BATCH_SIZE = 1000


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _is_first_of_month(current_date):
    """Return True if `current_date` ('YYYY-MM-DD') is the 1st of
    the month (the prune trigger).

    Defensive — returns False for None / malformed dates so a
    corrupt clock doesn't trigger a spurious prune.
    """
    if not current_date or len(current_date) < 10:
        return False
    # 'YYYY-MM-DD' — day-of-month is chars [8:10]. '01' = 1st.
    return current_date[8:10] == "01"


def _prune_fight_beats(conn, current_date):
    """DELETE fight_beats rows whose fight's event is completed + past.

    Special-case prune for fight_beats — the fastest-growing table.
    fight_beats has no `is_completed` flag of its own; eligibility
    is determined by a JOIN to fights → events:

        DELETE FROM fight_beats WHERE fight_id IN (
          SELECT f.fight_id FROM fights f
          JOIN events e ON e.event_id = f.event_id
          WHERE e.status = 'completed'
            AND date(e.event_date) < date(?, '-1 day')
        )

    The 1-day grace window keeps beats for events that completed
    TODAY (the UI's Fight Night replay may still be reading them).
    Beats for events that completed YESTERDAY OR EARLIER are deleted
    — they're never read again after the event day.

    BATCHED to _BATCH_SIZE rows per call so a single prune tick
    doesn't lock the DB for seconds on huge tables. If a batch
    fills, the next day's tick prunes the next _BATCH_SIZE.

    Args:
        conn: sqlite3.Connection (caller commits).
        current_date: 'YYYY-MM-DD' sim date.

    Returns:
        Number of rows deleted (int).
    """
    if not current_date:
        return 0
    # Fetch the rowids to delete (LIMIT _BATCH_SIZE). Using rowid
    # is faster than fetching the explicit PK + works on every table.
    select_sql = (
        "SELECT fb.rowid FROM fight_beats fb "
        "JOIN fights f ON f.fight_id = fb.fight_id "
        "JOIN events e ON e.event_id = f.event_id "
        "WHERE e.status = 'completed' "
        "AND date(e.event_date) < date(?, '-1 day') "
        f"LIMIT {int(_BATCH_SIZE)}"
    )
    try:
        rows = conn.execute(select_sql, (current_date,)).fetchall()
    except sqlite3.DatabaseError:
        # Defensive — if fight_beats / fights / events don't exist
        # (shouldn't happen post-v3.x), silently no-op.
        return 0
    if not rows:
        return 0
    rowids = [r[0] for r in rows]
    placeholders = ",".join("?" for _ in rowids)
    cur = conn.execute(
        f"DELETE FROM fight_beats WHERE rowid IN ({placeholders})",
        rowids,
    )
    return cur.rowcount or 0


def _current_sim_date(conn):
    """Return simulation_clock.current_date, or None."""
    try:
        row = conn.execute(
            "SELECT simulation_clock.current_date "
            "FROM simulation_clock WHERE clock_id=1"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.DatabaseError:
        return None


def _prune_table(conn, table, date_column, max_age_days, extra_where):
    """DELETE up to _BATCH_SIZE rows from `table` older than
    `max_age_days` (computed from `date_column`).

    Uses a subquery to fetch the IDs to delete (SQLite's
    DELETE ... LIMIT doesn't compose with WHERE directly, so we use
    the rowid-IN-subquery pattern — equivalent performance).

    Args:
        conn: sqlite3.Connection (caller commits).
        table: target table name (validated against _PRUNE_POLICY —
            this module only deletes from the 7 whitelisted tables).
        date_column: the column to compare against current_date.
        max_age_days: rows older than this many days are pruned.
        extra_where: optional SQL fragment (e.g. "is_active = 0")
            restricting which rows are eligible.

    Returns:
        Number of rows deleted (int). 0 if nothing eligible.
    """
    # Build the WHERE clause. The age comparison uses SQLite's date()
    # function: rows older than max_age_days satisfy
    #   date(current_date, '-N days') > date(table.date_column)
    # i.e. the cutoff date is later (more recent) than the row's date.
    where_parts = [f"date(?, '-{int(max_age_days)} days') > date({date_column})"]
    if extra_where:
        where_parts.append(f"({extra_where})")
    where_clause = " AND ".join(where_parts)

    # Fetch the rowids to delete (LIMIT _BATCH_SIZE). Using rowid
    # (SQLite's implicit primary key) is faster than fetching the
    # explicit PK and works on every table.
    select_sql = (
        f"SELECT rowid FROM {table} "
        f"WHERE {where_clause} "
        f"LIMIT {int(_BATCH_SIZE)}"
    )
    rows = conn.execute(select_sql, (_current_sim_date(conn) or "1970-01-01",)).fetchall()
    if not rows:
        return 0
    rowids = [r[0] for r in rows]
    # DELETE in one statement (executemany would be 1 round-trip per
    # rowid; a single DELETE with IN (...) is 1 round-trip total).
    placeholders = ",".join("?" for _ in rowids)
    delete_sql = f"DELETE FROM {table} WHERE rowid IN ({placeholders})"
    cur = conn.execute(delete_sql, rowids)
    return cur.rowcount or 0


def _run_monthly_prune(conn, current_date):
    """Run the monthly prune across all 8 tables.

    Args:
        conn: sqlite3.Connection (caller commits).
        current_date: the current sim date string ('YYYY-MM-DD').

    Returns:
        Dict mapping table_name → rows_deleted (int). Keys with 0
        deletions are still included (the print shows all 8 tables).
    """
    results = {}
    for table, date_column, max_age_days, extra_where in _PRUNE_POLICY:
        try:
            # Special case: fight_beats — only delete beats for
            # fights whose event is completed + past. The generic
            # _prune_table path uses date(fight_beats.created_at)
            # which doesn't capture the event-completion semantics
            # (created_at is set when the beat is written, not when
            # the event completes — a fight resolved today has beats
            # with created_at=today, but we want to keep those until
            # tomorrow). Use the JOIN-based prune instead.
            if table == "fight_beats":
                n = _prune_fight_beats(conn, current_date)
            else:
                n = _prune_table(conn, table, date_column,
                                 max_age_days, extra_where)
            results[table] = n
        except sqlite3.DatabaseError as e:
            # Defensive — a corrupt table or missing column shouldn't
            # crash the prune. Log + continue with the other tables.
            print(f"WARNING: pruning_svc failed on {table}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            results[table] = 0
    return results


# ----------------------------------------------------------------
# TICK_ADVANCED subscriber
# ----------------------------------------------------------------

def _on_tick_advanced(conn, event):
    """Subscriber for TICK_ADVANCED — runs the prune.

    TIER1-365DAY (2027-02): now does TWO things:
      1. DAILY: prune fight_beats (the fastest-growing table). Runs
         on EVERY tick so the table stays bounded to ~1 day of beats.
         fight_beats is only needed during fight resolution + show_
         rating + morale + Fight Night UI display — all on the event
         day. After the event completes, fight_beats is NEVER read
         again. Keeping ~2K rows (1 day of beats) instead of 286K
         rows (5 years of beats) saves ~50ms/tick on every news /
         fight query that JOINs fight_beats.
      2. MONTHLY: run the full 8-table prune (news_items, daily_
         headlines, social_posts, injuries, suspensions, training_
         camps, scouting_reports, fight_beats) on the 1st of each
         in-game month. Same as before — fight_beats is included so
         a missed daily tick is caught by the monthly sweep.

    The function does NOT commit — the caller (run_tick) commits
    after publish() returns, matching the established pattern. The
    prune DELETEs are visible to the post-commit daily interpretation
    pass + the next tick's queries.

    Defensive — any failure is caught + logged. A prune failure
    MUST NOT crash the simulation (the worst case is the DB grows
    larger than ideal — a slow DB is recoverable; a crashed sim is
    not).
    """
    current_date = event.get('current_date') or _current_sim_date(conn)
    if not current_date:
        return

    # ---- DAILY fight_beats prune (every tick) ----
    # Runs BEFORE the monthly check so it always fires — fight_beats
    # grows fast enough that a monthly prune alone lets it balloon
    # to 30× the steady-state size between month-ends.
    try:
        fb_deleted = _prune_fight_beats(conn, current_date)
    except Exception as e:
        print(f"WARNING: pruning_svc daily fight_beats prune crashed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        fb_deleted = 0

    # ---- MONTHLY full prune (1st of month only) ----
    if not _is_first_of_month(current_date):
        # Not the 1st — only the daily fight_beats prune ran. Print
        # a heartbeat only when rows were actually deleted (avoids
        # spamming the log with 0-row prints on every tick).
        if fb_deleted > 0:
            print(f"[pruning] Daily: pruned {fb_deleted} fight_beats")
        return
    try:
        results = _run_monthly_prune(conn, current_date)
    except Exception as e:
        print(f"WARNING: pruning_svc monthly prune crashed: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return
    # Always print the summary on the 1st of the month (even if 0
    # rows were pruned) so the operator can see the prune ran. The
    # brief's expected format:
    #   "[pruning] Pruned X news_items, Y daily_headlines, Z social_posts, ..."
    # When nothing was pruned, the print still fires with 0 counts —
    # this is the "heartbeat" that confirms the service is alive.
    parts = [f"{n} {table}" for table, n in results.items()]
    print("[pruning] Pruned " + ", ".join(parts))


# ----------------------------------------------------------------
# Registration
# ----------------------------------------------------------------

def register_subscribers():
    """Register the pruning subscriber on the event bus.

    Call once at startup (UI App.__init__, run_sim_forward.py, test
    setup). Safe to call multiple times — the event bus's subscribe()
    simply appends to its subscriber list. For test isolation, call
    reset_bus() first to clear any prior registrations.

    Subscribes to:
      TICK_ADVANCED → _on_tick_advanced (daily check; monthly prune
                      on the 1st of each in-game month)
    """
    from event_bus import get_bus, Events
    bus = get_bus()
    bus.subscribe(
        Events.TICK_ADVANCED, _on_tick_advanced,
        name="pruning_svc.on_tick_advanced",
    )
