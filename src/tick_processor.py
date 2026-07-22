import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

# Make src/ importable so we can call _vacate_title_on_retirement and
# generate_fighter from app.py. app.py imports tkinter, but importing
# the module itself does NOT require a display (only tk.Tk() does), so
# this is safe in headless contexts. There is no circular-import risk
# because app.py does NOT import tick_processor.
sys.path.insert(0, str(BASE_DIR))
from app import _vacate_title_on_retirement, generate_fighter  # noqa: E402


# ----------------------------------------------------------------
# Retirement checking (Task ID 12, extended in Task ID 14).
#
# Fighters age. When a fighter crosses age 40 with declining
# career_health, they retire. Age 45 is mandatory retirement
# (regardless of health). Retiring champions vacate their titles
# (delegated to app._vacate_title_on_retirement). A news item is
# written per retirement.
#
# Task ID 14 added the regen hook: each retirement also generates a
# replacement fighter (via app.generate_fighter) with the same
# fight_style_archetype_id (style DNA). The new fighter enters as a
# free agent and a regen_lineage row is recorded linking the retiring
# fighter to the replacement (for future memory-resurfacing features).
#
# This function runs on every tick (called from run_tick after the
# clock advance). It does NOT commit — the caller commits. This
# matches the existing pattern in app.py where every helper leaves
# the commit to the outermost caller.
#
# Foundation for:
#   - Task 14 (regen) — retiring fighters trigger generate_fighter.
#   - Task 11 (titles) — retiring champions vacate the belt (handled
#     by _vacate_title_on_retirement in app.py).
#   - The "playable forever" loop — without retirement + regen, the
#     roster shrinks permanently and eventually empties.
# ----------------------------------------------------------------

def _check_retirements(conn, current_date):
    """Check all active fighters for retirement eligibility and retire them.

    Retirement rules (Task ID 12):
      - A fighter is retirement-eligible if:
        (a) age >= 40 (computed from date_of_birth and current_date), AND
        (b) career_health < 60 (declining health — a healthy 40-year-old
            can keep fighting, but a worn-down one should hang it up).
      - OR age >= 45 (mandatory retirement — no one fights past 45 in
        this sim, regardless of health).
      - When a fighter retires:
        (a) Set fighters.is_active = 0, fighters.is_retired = 1,
            fighters.updated_at = CURRENT_TIMESTAMP.
        (b) Vacate any title they hold (call
            _vacate_title_on_retirement from app.py).
        (c) Write a news item announcing the retirement.
        (d) Task ID 14: generate a replacement fighter via
            app.generate_fighter (inherits the retiring fighter's
            fight_style_archetype_id as style DNA; enters as a free
            agent) and record a regen_lineage row linking the retiring
            fighter to the replacement.
      - Returns the list of retired fighter_ids (for logging/testing).

    Args:
        conn: sqlite3 connection (caller commits).
        current_date: ISO date string 'YYYY-MM-DD' (the current sim date).

    Returns:
        List of fighter_ids that were retired on this tick.
    """
    try:
        current_dt = datetime.strptime(current_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        # Defensive: if current_date is somehow malformed, skip the
        # retirement check entirely (return empty list). The clock
        # advance in run_tick will still commit; the next tick will
        # try again.
        return []

    # Fetch all active, non-retired fighters with their DOB + career
    # health. LEFT JOIN fighter_career so a fighter without a career
    # row (defensive — shouldn't happen with the seed) is treated as
    # career_health=100 (healthy, won't retire on the health rule).
    # We also pull fight_style_archetype_id so we can pass it to the
    # regen_lineage INSERT below (Task ID 14 — the new replacement
    # fighter inherits the retiring fighter's style DNA).
    rows = conn.execute(
        "SELECT f.fighter_id, f.first_name, f.last_name, f.date_of_birth, "
        "f.fight_style_archetype_id, "
        "COALESCE(fc.career_health, 100) AS career_health "
        "FROM fighters f "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
        "WHERE f.is_active = 1 AND f.is_retired = 0"
    ).fetchall()

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news). The seeded DB already has this source.
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    retired = []
    for fighter_id, first_name, last_name, dob, style_archetype_id, career_health in rows:
        # Compute age: years between dob and current_date, adjusted
        # down by 1 if the birthday hasn't happened yet this year.
        # Comparing (month, day) tuples handles leap-year babies
        # correctly (Feb 29 vs Feb 28 in non-leap years).
        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
        except (ValueError, TypeError):
            # Defensive: skip fighters with malformed DOB. (Shouldn't
            # happen with the seed, but a future regen engine or mod
            # tool could produce one.)
            continue
        age = current_dt.year - dob_dt.year
        if (current_dt.month, current_dt.day) < (dob_dt.month, dob_dt.day):
            age -= 1

        # Eligibility: age >= 45 (mandatory) OR (age >= 40 AND
        # career_health < 60). The brief specifies `< 60` for the
        # health threshold — a fighter with career_health exactly 60
        # does NOT retire (boundary case tested in test_retirement.py
        # case D).
        eligible = (age >= 45) or (age >= 40 and career_health < 60)
        if not eligible:
            continue

        # Retire the fighter. is_active=0 means _pick_matchup (Task 8)
        # and any future "available fighters" queries will skip them.
        # is_retired=1 distinguishes "retired" from "inactive for
        # another reason" (e.g., injury in Task 15, suspension in a
        # future task). Both flags are set together here.
        conn.execute(
            "UPDATE fighters SET is_active = 0, is_retired = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE fighter_id = ?",
            (fighter_id,),
        )

        # Vacate any title the retiring fighter holds. Returns the
        # list of vacated title_ids (empty list if they held none).
        # The helper writes its own news item per vacation, so we
        # don't write a duplicate one here.
        _vacate_title_on_retirement(conn, fighter_id, current_date)

        # Write the retirement news item. topic='retirement' so the
        # future news engine (Task 23) can filter retirement-themed
        # items. fighter_id is set so future UIs can filter "this
        # fighter's news". promotion_id is left NULL (the news is
        # about the fighter, not a specific promotion — a fighter can
        # retire from one promotion and sign with another in Task 13).
        full_name = f"{first_name} {last_name}"
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                src_id,
                f"{full_name} announces retirement at age {age}",
                f"After a long career, {full_name} has announced retirement "
                f"from professional MMA competition at age {age}.",
                "neutral",
                "retirement",
                fighter_id,
                current_date,
            ),
        )

        # ----------------------------------------------------------------
        # Regen engine (Task ID 14). When a fighter retires, generate
        # a replacement fighter from the name pools with the same
        # fight_style_archetype_id (style DNA). The new fighter enters
        # as a free agent (current_promotion_id=NULL, is_active=1,
        # is_retired=0) so they appear in Task 13's Free Agents tab
        # and can be signed by any promotion. Record the regen_lineage
        # row linking the retiring fighter to the replacement (for
        # future memory-resurfacing features in Stage 3+).
        #
        # The replacement fighter's fighter_id is appended to the
        # `retired` list returned by this function (alongside the
        # retiring fighter's fighter_id) so the caller can log both.
        # We don't append to `retired` here — that list is "fighters
        # retired on this tick", and the replacement isn't retired.
        # The replacement_id is logged via a separate print in
        # run_tick (see below).
        #
        # v2.0.1 (Task pre-B1-fixes): champion-successor memory
        # resurfacing. After generating the replacement, check whether
        # the retiring fighter was ever a champion (fighter_career.
        # title_reigns > 0). If YES:
        #   - Create a fighter_memory_links row with link_type=
        #     'successor' linking the new fighter to the retiring
        #     champion. link_strength is based on title_reigns (more
        #     reigns = stronger link): min(50 + 10*reigns, 100).
        #   - Write a "comparisons to former champion {name}" news
        #     item with topic='legacy' (separate from the standard
        #     'prospect' news generate_fighter already wrote). This
        #     is the memory-resurfacing payoff: the world remembers
        #     who the retiring champion was and draws the comparison
        #     to the new prospect.
        # If NO (non-champion retirement): no memory link, no extra
        # news. The standard "new prospect emerges" news from
        # generate_fighter is enough — keeps the world alive without
        # cheapening the memory-resurfacing feature.
        # ----------------------------------------------------------------
        replacement_id = generate_fighter(
            conn,
            style_dna_source_id=fighter_id,  # inherit retiring fighter's style archetype
            current_date=current_date,
        )
        if replacement_id is not None:
            # Record the regen lineage. style_dna_archetype_id is the
            # retiring fighter's archetype (already fetched above) —
            # the replacement inherits it via generate_fighter.
            # INSERT OR IGNORE protects against the (theoretically
            # impossible) case of duplicate (retiring, replacement)
            # pairs — the UNIQUE constraint on regen_lineage enforces
            # this. regen_date is the sim date the retirement happened
            # on (NOT CURRENT_TIMESTAMP which is wall-clock time).
            conn.execute(
                "INSERT OR IGNORE INTO regen_lineage (retiring_fighter_id, "
                "replacement_fighter_id, style_dna_archetype_id, regen_date) "
                "VALUES (?, ?, ?, ?)",
                (fighter_id, replacement_id, style_archetype_id, current_date),
            )

            # v2.0.1 (Task pre-B1-fixes): champion-successor memory
            # resurfacing. Check whether the retiring fighter was
            # ever a champion. The fighter_career.title_reigns column
            # is the cleanest, most reliable signal — it's incremented
            # by _resolve_title_after_fight() in app.py every time
            # the fighter wins a title (vacant title claimed OR
            # reigning champion dethroned). COALESCE(..., 0) is
            # defensive: a fighter without a career row (shouldn't
            # happen with the seed) is treated as non-champion.
            reigns_row = conn.execute(
                "SELECT COALESCE(fc.title_reigns, 0) "
                "FROM fighter_career fc "
                "WHERE fc.fighter_id = ?",
                (fighter_id,),
            ).fetchone()
            retiring_reigns = reigns_row[0] if reigns_row else 0

            if retiring_reigns > 0:
                # The retiring fighter was a champion. Create the
                # fighter_memory_links 'successor' row linking the
                # new prospect to the retiring champion. link_strength
                # is based on title_reigns: 1 reign = 60, 2 = 70,
                # 3 = 80, 4 = 90, 5+ = 100 (capped). More reigns =
                # stronger link (a 5-reign champion's successor is a
                # MUCH bigger deal than a 1-reign champion's
                # successor). INSERT OR IGNORE protects against the
                # UNIQUE (fighter_id, linked_fighter_id, link_type)
                # constraint — duplicate successor links (theoretically
                # impossible since regen_lineage also has UNIQUE on
                # retiring+replacement pairs) are silently skipped.
                link_strength = min(50 + 10 * retiring_reigns, 100)
                conn.execute(
                    "INSERT OR IGNORE INTO fighter_memory_links "
                    "(fighter_id, linked_fighter_id, link_type, "
                    "link_strength) VALUES (?, ?, 'successor', ?)",
                    (replacement_id, fighter_id, link_strength),
                )

                # Write the champion-successor comparison news item.
                # topic='legacy' so future UI filters can group
                # memory-resurfacing news together (separate from
                # 'prospect' news the standard generate_fighter
                # already wrote, and from 'retirement' news the
                # retirement announcement already wrote). The
                # headline follows the brief's exact wording: "New
                # prospect {name} emerges on the scene — fight fans
                # are already drawing comparisons to former champion
                # {retiring_fighter_name}." fighter_id is set to the
                # NEW fighter (the prospect) so future UIs can filter
                # "this prospect's news". published_at=current_date.
                replacement_name_row = conn.execute(
                    "SELECT first_name || ' ' || last_name "
                    "FROM fighters WHERE fighter_id = ?",
                    (replacement_id,),
                ).fetchone()
                replacement_name = (
                    replacement_name_row[0]
                    if replacement_name_row
                    else f"Fighter {replacement_id}"
                )
                conn.execute(
                    "INSERT INTO news_items (news_source_id, headline, "
                    "body, sentiment, topic, fighter_id, published_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        src_id,
                        f"New prospect {replacement_name} emerges on "
                        f"the scene — fight fans are already drawing "
                        f"comparisons to former champion {full_name}",
                        f"A new talent, {replacement_name}, has arrived "
                        f"as a free agent. Fans and pundits are already "
                        f"drawing comparisons to former champion "
                        f"{full_name}, who retired with "
                        f"{retiring_reigns} title reign(s) to their "
                        f"name. Only time will tell whether the "
                        f"comparisons hold up.",
                        "positive",
                        "legacy",
                        replacement_id,
                        current_date,
                    ),
                )
            # Non-champion retirement: no memory link, no extra news.
            # The standard "new prospect emerges" news from
            # generate_fighter is the only prospect news — keeps the
            # world alive without cheapening the memory-resurfacing
            # feature.

        retired.append(fighter_id)

    return retired


# ----------------------------------------------------------------
# Contract expiry (Task ID 13).
#
# When a fighter's contract end_date passes the current sim date,
# the contract transitions to 'expired' and the fighter becomes a
# free agent (current_promotion_id = NULL). This is the talent-
# circulation foundation for:
#   - Task 25 (rival promotion AI) — RFL signs free agents.
#   - Task 14 (regen) — new generated fighters enter as free agents.
#   - The "playable forever" loop — without free agency the roster
#     is static.
#
# Rules:
#   - For each contract with status='active' AND end_date < current_date:
#     (a) Set contracts.status = 'expired', contracts.updated_at =
#         CURRENT_TIMESTAMP.
#     (b) If the contract is a fighter contract
#         (contract_target_type='fighter' AND the linked fighter is
#         NOT retired), set the fighter's current_promotion_id = NULL
#         and is_active = 1 (they're still active, just unsigned). The
#         is_retired check is important: a retired fighter whose
#         contract also expired on this tick was retired FIRST by
#         _check_retirements (which runs before this function in
#         run_tick). Setting current_promotion_id = NULL on a retired
#         fighter would be misleading — they're not a free agent,
#         they're retired. So we skip that update for retired fighters.
#     (c) For fighter contracts (non-retired), write a news item:
#         "<fighter> becomes a free agent".
#   - Staff / broadcast contracts also expire (status -> 'expired')
#     but they don't have a current_promotion_id column on the
#     fighters table — they're in the `staff` table — so no fighter
#     update happens, and no news item is written for them (the
#     player-facing UI doesn't surface staff contract expiry).
#   - Returns the list of (contract_id, fighter_id_or_None) tuples
#     that expired (fighter_id is None for staff/broadcast contracts,
#     or for fighter contracts whose fighter is already retired).
#
# This function runs on every tick (called from run_tick AFTER
# _check_retirements, so a retired-and-contract-expiring fighter is
# handled correctly). It does NOT commit — the caller commits.
# ----------------------------------------------------------------

def _check_contract_expiry(conn, current_date):
    """Expire contracts past their end_date and set fighters as free agents.

    Rules (Task ID 13):
      - For each contract with status='active' AND end_date < current_date:
        (a) Set contracts.status = 'expired', contracts.updated_at =
            CURRENT_TIMESTAMP.
        (b) If the contract is a fighter contract
            (contract_target_type='fighter') AND the linked fighter is
            NOT already retired, set the fighter's current_promotion_id
            = NULL (they become a free agent). Also set is_active = 1
            (they're still active, just unsigned — defensive in case
            they were marked inactive for some other reason). Retired
            fighters are skipped: they're not free agents, they're
            retired.
        (c) For fighter contracts whose fighter is not retired, write a
            news item: "<fighter> becomes a free agent". topic='signing'
            (so future UI filters can group signing-related news
            together), fighter_id set, published_at=current_date.
      - Staff/broadcast contracts (contract_target_type='staff' or
        'broadcast') also expire but don't set current_promotion_id
        (staff don't have that column) and don't get a news item.
      - Returns the list of (contract_id, fighter_id_or_None) tuples
        that expired. fighter_id is None for staff/broadcast contracts
        and for fighter contracts whose fighter is already retired.

    Args:
        conn: sqlite3 connection (caller commits).
        current_date: ISO date string 'YYYY-MM-DD' (the current sim date).

    Returns:
        List of (contract_id, fighter_id) tuples for contracts that
        expired on this tick. fighter_id is None for staff/broadcast
        contracts and for fighter contracts whose fighter is already
        retired.
    """
    # Fetch active contracts past their end_date. LEFT JOIN
    # fighter_contracts to pick up the fighter_id (NULL for staff/
    # broadcast contracts). LEFT JOIN fighters to get the name +
    # is_retired flag (we only want to set current_promotion_id=NULL
    # for non-retired fighters).
    rows = conn.execute(
        "SELECT c.contract_id, c.contract_target_type, "
        "fc.fighter_id, f.first_name, f.last_name, f.is_retired "
        "FROM contracts c "
        "LEFT JOIN fighter_contracts fc ON fc.contract_id = c.contract_id "
        "LEFT JOIN fighters f ON f.fighter_id = fc.fighter_id "
        "WHERE c.status = 'active' AND c.end_date < ?",
        (current_date,),
    ).fetchall()

    if not rows:
        return []

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news and _check_retirements). The seeded DB already
    # has this source.
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name = 'System Feed'"
    ).fetchone()
    if src_row is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src_row[0]

    expired = []
    for contract_id, target_type, fighter_id, first_name, last_name, is_retired in rows:
        # (a) Mark the contract as expired.
        conn.execute(
            "UPDATE contracts SET status = 'expired', "
            "updated_at = CURRENT_TIMESTAMP WHERE contract_id = ?",
            (contract_id,),
        )

        # (b) For fighter contracts whose fighter is NOT retired, set
        # current_promotion_id = NULL (free agent). is_retired check
        # is critical: a retired fighter whose contract also expired
        # on this tick was retired FIRST by _check_retirements (which
        # runs before this function in run_tick). Setting
        # current_promotion_id = NULL on a retired fighter would be
        # misleading — they're not a free agent, they're retired.
        if target_type == 'fighter' and fighter_id is not None and is_retired != 1:
            conn.execute(
                "UPDATE fighters SET current_promotion_id = NULL, "
                "is_active = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE fighter_id = ?",
                (fighter_id,),
            )
            # (c) Write the free-agency news item.
            full_name = f"{first_name} {last_name}"
            conn.execute(
                "INSERT INTO news_items (news_source_id, headline, body, "
                "sentiment, topic, fighter_id, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    src_id,
                    f"{full_name} becomes a free agent",
                    f"{full_name}'s contract has expired and they are now "
                    f"a free agent, available to sign with any promotion.",
                    "neutral",
                    "signing",
                    fighter_id,
                    current_date,
                ),
            )
            expired.append((contract_id, fighter_id))
        else:
            # Staff/broadcast contract, OR fighter contract for an
            # already-retired fighter. No fighter update, no news item.
            expired.append((contract_id, None))

    return expired


def run_tick(conn, tick_type="day", steps=1):
    for _ in range(steps):
        # v2.0.0 (Task 14.7): qualify current_date (and the other
        # clock columns, for consistency) as simulation_clock.current_date
        # etc. to avoid the pre-existing SQLite quirk (§Z.6 in
        # SCHEMA_DRIFT_AUDIT.md) where bare `current_date` resolves to
        # SQLite's built-in date FUNCTION (today's wall-clock date)
        # instead of the simulation_clock.current_date COLUMN. This
        # caused the sim clock to jump from the seeded 2026-07-20 to
        # today+1 on the first tick. The new acceptance test
        # test_fighter_attributes.py case F verifies the tick now
        # advances by exactly 1 day from the seeded date.
        row = conn.execute("SELECT simulation_clock.current_date, simulation_clock.current_day, simulation_clock.current_week, simulation_clock.current_month, simulation_clock.current_year FROM simulation_clock WHERE clock_id=1").fetchone()
        dt = datetime.strptime(row[0], "%Y-%m-%d") + timedelta(days=1)
        day = row[1] + 1
        week = ((day - 1) // 7) + 1
        conn.execute(
            "UPDATE simulation_clock SET current_date=?, current_day=?, current_week=?, current_month=?, current_year=?, current_tick_type=?, tick_counter=tick_counter+1, updated_at=CURRENT_TIMESTAMP WHERE clock_id=1",
            (dt.strftime("%Y-%m-%d"), day, week, dt.month, dt.year, tick_type),
        )
        # Task ID 12: check for retirements on every tick. Runs AFTER
        # the clock advance so the retirement check uses the NEW sim
        # date (a fighter who turns 40 on this tick's new date becomes
        # eligible today, not yesterday). The function does NOT commit
        # — the conn.commit() below covers both the clock UPDATE and
        # any retirement side effects (fighters UPDATE, titles UPDATE,
        # news_items INSERTs). Task ID 14: each retirement also triggers
        # generate_fighter() which adds a replacement fighter + writes
        # the new-prospect news item + records the regen_lineage row.
        # Prints a one-line log per tick if any fighters were retired,
        # mirroring the pattern in resolve_next_fight's auto-schedule
        # warning.
        retired = _check_retirements(conn, dt.strftime("%Y-%m-%d"))
        if retired:
            print(f"  Retired {len(retired)} fighter(s) on "
                  f"{dt.strftime('%Y-%m-%d')}: {retired}")
            # Task ID 14: log regens alongside retirements. Each retired
            # fighter spawned a replacement — query regen_lineage to
            # find the replacement_ids.
            regens = conn.execute(
                "SELECT retiring_fighter_id, replacement_fighter_id "
                "FROM regen_lineage WHERE regen_date = ?",
                (dt.strftime("%Y-%m-%d"),),
            ).fetchall()
            if regens:
                print(f"  Generated {len(regens)} replacement fighter(s) on "
                      f"{dt.strftime('%Y-%m-%d')}: {regens}")
        # Task ID 13: check for contract expiry on every tick. Runs
        # AFTER _check_retirements so a retired-and-contract-expiring
        # fighter is handled correctly: _check_retirements sets
        # is_retired=1 first, then _check_contract_expiry sees
        # is_retired=1 and skips the current_promotion_id=NULL update
        # (they're retired, not a free agent). The function does NOT
        # commit — the conn.commit() below covers both the clock
        # UPDATE and any contract-expiry side effects (contracts
        # UPDATE, fighters UPDATE, news_items INSERTs). Prints a one-
        # line log per tick if any contracts expired.
        expired = _check_contract_expiry(conn, dt.strftime("%Y-%m-%d"))
        if expired:
            print(f"  Expired {len(expired)} contract(s) on "
                  f"{dt.strftime('%Y-%m-%d')}: {expired}")
        conn.commit()

def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        run_tick(conn, "day", 1)
    print("Tick advanced.")

if __name__ == "__main__":
    main()
