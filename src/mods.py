"""CAGE EMPIRE Mod Tools Skeleton (Stage 5 — Task 29 / Stage5-Final).

Skeleton module for the modding UI. Per docs/STAGES.md Task ID 29:
"New `src/mods.py` module. Fighter / promotion / venue / contract
editors. CSV + JSON import/export. Portrait pack folder support.
Full database backup/restore."

This task ships the SKELETON (functions + defensive validation, no
UI). A future task wires these functions into a ttk.Toplevel mod
tools dialog. The functions are designed to be called directly by
the UI — they take a sqlite3 connection and return simple types
(booleans, lists, dicts) that the UI can display.

CONVENTIONS compliance:
  §5  — One table-group per task. This task adds NO new tables —
        it is code-only. The functions read/write existing tables
        (fighters, promotions, fighter_attributes, fighter_personality,
        fighter_career). Per the brief: "Mod tools skeleton (Task 29,
        code-only, no schema change)."
  §6  — Smoke test protocol followed. The acceptance test rebuilds
        the DB, then exercises export_fighters_csv / edit_fighter /
        backup_database.
  §10 — Dynamic-version pattern. The acceptance test reads
        build_db.CODE_SCHEMA_VERSION at test time.
  §13 — Design Law: Puppet Master fantasy ("The sport evolves
        because of my decisions"). The mod tools let the player
        directly shape the world — rename a fighter, fix a contract,
        boost a prospect's potential, demote a champion. The player
        is the author of the world, not just a participant. This is
        the deepest expression of the Puppet Master fantasy.
  §14 — Voice Layer: mod tools deal in RAW values (the player is
        editing the sim directly, not reading a narrative). The
        export CSVs contain raw attribute numbers, the edit_fighter
        function takes raw field values. This is the ONE place
        where raw numbers are appropriate — the player has chosen
        to mod, which is a debug/authoring mode. Per the brief:
        "defensive — validates column names against the schema."
        No voice descriptors in the mod tools.
  §15 — Event Bus: NOT used. Mod tools are player-initiated (the
        player clicks a button in the UI), not event-driven. No
        subscribers registered.

DESIGN DECISIONS:
  - Skeleton functions (no UI). The UI is a follow-up task that
    will wire these into ttk widgets.
  - Defensive column validation in edit_fighter / edit_promotion.
    The functions accept **kwargs and validate every key against
    the table's actual columns (via PRAGMA table_info). This
    prevents the player from accidentally writing to a non-existent
    column (typo: 'nicname' instead of 'nickname') and corrupting
    the DB. Invalid keys are silently dropped (defensive — refuse
    to write, log nothing).
  - backup_database / restore_database wrap save_load.save_game /
    load_game. This reuses the existing save/load infrastructure
    (shutil.copy2 + metadata JSON). The mod tools don't reinvent
    the backup format — they use the same one the player uses for
    manual saves.
  - export_fighters_csv uses Python's csv module (standard library).
    The CSV includes a header row + one row per fighter. The columns
    are fighters.* + fighter_attributes.* + fighter_personality.* +
    fighter_career.* — the full data shape. The CSV is human-readable
    and round-trips through import_fighters_csv.
  - import_fighters_csv uses upsert by fighter_id (INSERT OR REPLACE).
    This is destructive — if the player imports a CSV with a
    fighter_id that already exists, the existing row is overwritten.
    The function is defensive: it validates the CSV header against
    the table columns and skips unknown columns.
  - export_promotions_json uses Python's json module. JSON is more
    readable than CSV for the promotions table (which has fewer rows
    but more complex columns like ai_aggression, broadcast_tier,
    etc.). The JSON is a list of dicts, one per promotion.

USAGE:
  from mods import (export_fighters_csv, import_fighters_csv,
      export_promotions_json, backup_database, restore_database,
      edit_fighter, edit_promotion)

  # Export all fighters to a CSV.
  export_fighters_csv(conn, 'data/exports/fighters.csv')

  # Edit a fighter's nickname.
  edit_fighter(conn, fighter_id=1, nickname='The Hammer')

  # Backup the DB (uses save_load.save_game internally).
  backup_database(filepath='data/saves/pre_mod_backup')

  # Restore from a backup (uses save_load.load_game internally).
  new_conn = restore_database('data/saves/pre_mod_backup')
"""

import csv
import json
import sqlite3
from pathlib import Path


# ----------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------

def _table_columns(conn, table):
    """Return the list of column names for a table (defensive).

    Uses PRAGMA table_info — the canonical way to introspect a
    SQLite table's columns. Returns an empty list if the table
    doesn't exist (defensive — caller should handle).
    """
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return []
    # PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk).
    return [r[1] for r in rows]


def _filter_valid_columns(conn, table, kwargs):
    """Filter a kwargs dict to only keys that are actual columns on
    the table. Returns a new dict.

    Defensive — drops keys that don't match any column (prevents
    typos like 'nicname' instead of 'nickname' from silently
    failing OR worse, writing to the wrong column). The caller
    can inspect the returned dict to detect dropped keys.
    """
    valid_cols = set(_table_columns(conn, table))
    return {k: v for k, v in kwargs.items() if k in valid_cols}


# ----------------------------------------------------------------
# CSV / JSON import-export
# ----------------------------------------------------------------

def export_fighters_csv(conn, filepath):
    """Export all fighters + attributes + personality + career to CSV.

    Writes a CSV with a header row + one row per fighter. The columns
    are the union of fighters.*, fighter_attributes.*, fighter_
    personality.*, fighter_career.* (prefixed with the table name to
    avoid collisions — e.g., 'fighters_fighter_id', 'fighter_attrs_
    punch_power'). The CSV is human-readable and round-trips through
    import_fighters_csv.

    Args:
        conn: sqlite3 connection (read-only query).
        filepath: path to the output CSV file (str or Path). Parent
            directory is created if it doesn't exist.

    Returns:
        The number of fighters exported (int). 0 if no fighters
        exist (the CSV still has the header row).
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Fetch all fighters with their attributes + personality + career
    # in one JOINed query. LEFT JOINs so fighters missing attribute /
    # personality / career rows still export (defensive — the seed
    # always creates all 3, but a partial DB or modded DB might not).
    rows = conn.execute(
        "SELECT f.*, fa.*, fp.*, fc.* "
        "FROM fighters f "
        "LEFT JOIN fighter_attributes fa ON fa.fighter_id=f.fighter_id "
        "LEFT JOIN fighter_personality fp ON fp.fighter_id=f.fighter_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "ORDER BY f.fighter_id"
    ).fetchall()

    # Build the column names from the cursor description. This gives
    # us the actual column names (qualified by table via the JOIN).
    # SQLite returns unqualified column names by default, so we
    # disambiguate by prefixing with the source table.
    cursor_desc = conn.execute(
        "SELECT f.*, fa.*, fp.*, fc.* "
        "FROM fighters f "
        "LEFT JOIN fighter_attributes fa ON fa.fighter_id=f.fighter_id "
        "LEFT JOIN fighter_personality fp ON fp.fighter_id=f.fighter_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "LIMIT 0"
    ).description
    # Build qualified column names. The order matches the SELECT.
    # Each table contributes its columns in PRAGMA table_info order.
    table_col_counts = {
        "fighters": len(_table_columns(conn, "fighters")),
        "fighter_attributes": len(_table_columns(conn, "fighter_attributes")),
        "fighter_personality": len(_table_columns(conn, "fighter_personality")),
        "fighter_career": len(_table_columns(conn, "fighter_career")),
    }
    headers = []
    for table, count in table_col_counts.items():
        cols = _table_columns(conn, table)
        for col in cols:
            headers.append(f"{table}.{col}")

    # Write the CSV.
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)

    return len(rows)


def import_fighters_csv(conn, filepath):
    """Import fighters from a CSV (upsert by fighter_id).

    Reads a CSV written by export_fighters_csv and upserts the rows
    into the DB. The CSV header must match the export format (table-
    qualified column names like 'fighters.fighter_id'). Unknown
    columns are silently dropped (defensive). Rows with a fighter_id
    that already exists are UPDATEd (preserves FK references from
    fight_participants, fight_history, etc. — these have ON DELETE
    RESTRICT / NO ACTION which would block INSERT OR REPLACE).
    Rows with a fighter_id that doesn't exist are INSERTed as new
    fighters.

    Uses SQLite's UPSERT syntax (INSERT ... ON CONFLICT(fighter_id)
    DO UPDATE SET ...) — available since SQLite 3.24+. This avoids
    the DELETE-then-INSERT pattern of INSERT OR REPLACE, which
    would trigger ON DELETE RESTRICT FK violations from
    fight_participants and fight_rounds.

    Args:
        conn: sqlite3 connection (caller commits).
        filepath: path to the input CSV file (str or Path).

    Returns:
        The number of fighters imported (int). 0 if the CSV is empty
        or the header doesn't match any known columns.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return 0

    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return 0  # empty file

        # Parse the headers into per-table column lists.
        # Each header is 'table.column'. We group by table.
        table_cols = {}  # table → list of (col_name, header_index)
        for idx, header in enumerate(headers):
            if "." not in header:
                continue
            table, col = header.split(".", 1)
            table_cols.setdefault(table, []).append((col, idx))

        if not table_cols:
            return 0  # no recognized headers

        # Validate columns against the schema (drop unknown).
        for table in list(table_cols.keys()):
            valid_cols = set(_table_columns(conn, table))
            table_cols[table] = [
                (col, idx) for col, idx in table_cols[table]
                if col in valid_cols
            ]
            if not table_cols[table]:
                del table_cols[table]

        if not table_cols:
            return 0

        n_imported = 0
        for row in reader:
            # Build the values per table.
            # For each table, extract the values from the row using
            # the column indices, then UPSERT (INSERT ... ON CONFLICT
            # DO UPDATE). The conflict target is fighter_id (UNIQUE
            # on every fighter_* table). This avoids the DELETE-
            # then-INSERT pattern of INSERT OR REPLACE, which would
            # trigger ON DELETE RESTRICT FK violations from
            # fight_participants (FK to fighters with ON DELETE
            # RESTRICT) and fight_rounds (FK to fighters with NO
            # ACTION — the default).
            for table, col_pairs in table_cols.items():
                cols = [c for c, _ in col_pairs]
                vals = [row[i] if i < len(row) else None for _, i in col_pairs]
                # Skip rows that don't have a fighter_id (can't upsert
                # without the conflict target).
                if "fighter_id" not in cols:
                    continue
                placeholders = ",".join("?" * len(cols))
                col_list = ",".join(cols)
                # Build the SET clause for the DO UPDATE part —
                # every column EXCEPT fighter_id (the conflict target).
                update_cols = [c for c in cols if c != "fighter_id"]
                if not update_cols:
                    continue
                set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
                try:
                    conn.execute(
                        f"INSERT INTO {table} ({col_list}) "
                        f"VALUES ({placeholders}) "
                        f"ON CONFLICT(fighter_id) DO UPDATE SET {set_clause}",
                        vals,
                    )
                except sqlite3.Error:
                    # Defensive — skip rows that fail (e.g., CHECK
                    # constraint, NOT NULL violation). The caller
                    # can inspect the DB to see which rows imported.
                    continue
            n_imported += 1

        return n_imported


def export_promotions_json(conn, filepath):
    """Export all promotions to JSON.

    Writes a JSON file containing a list of dicts, one per promotion.
    The dict keys are the column names from the promotions table
    (unqualified). The JSON is human-readable (indent=2) and
    round-trips through a future import_promotions_json (not in this
    skeleton).

    Args:
        conn: sqlite3 connection (read-only query).
        filepath: path to the output JSON file (str or Path). Parent
            directory is created if it doesn't exist.

    Returns:
        The number of promotions exported (int).
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    cols = _table_columns(conn, "promotions")
    if not cols:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
        return 0

    col_list = ",".join(cols)
    rows = conn.execute(
        f"SELECT {col_list} FROM promotions ORDER BY promotion_id"
    ).fetchall()

    promotions = []
    for row in rows:
        promotions.append({col: val for col, val in zip(cols, row)})

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(promotions, f, indent=2, default=str)

    return len(promotions)


# ----------------------------------------------------------------
# Backup / restore (wraps save_load)
# ----------------------------------------------------------------

def backup_database(filepath=None):
    """Backup the active DB to a save file (wraps save_load.save_game).

    Uses save_load.save_game internally — the same backup mechanism
    the player uses for manual saves. This means the mod tools
    backup is interchangeable with manual saves (the player can
    restore a mod-tools backup via the regular Load Game UI).

    Args:
        filepath: optional — name for the backup. If None, uses a
            timestamp-based name (save_YYYYMMDD_HHMMSS). The name
            is sanitized by save_load._sanitize_save_name (only
            [a-zA-Z0-9_-] allowed). The backup is written to
            data/saves/{name}.db + .json metadata.

    Returns:
        The sanitized backup name (str). The caller can use this
        to restore later (pass to restore_database).
    """
    import save_load
    import sqlite3
    from pathlib import Path

    # save_load.save_game needs a connection (it commits + queries
    # metadata). Open a fresh connection to the active DB path.
    conn = sqlite3.connect(save_load.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        save_name = save_load.save_game(conn, save_name=filepath)
    finally:
        conn.close()
    return save_name


def restore_database(filepath):
    """Restore the active DB from a backup (wraps save_load.load_game).

    Uses save_load.load_game internally — the same restore mechanism
    the player uses for manual loads. The backup file is copied back
    to the active DB path, overwriting the current DB. Returns a NEW
    sqlite3.Connection to the restored DB.

    The caller is responsible for closing any existing connection
    BEFORE calling restore_database — on Windows, you can't
    overwrite a file that's open by another process.

    Args:
        filepath: name of the backup to restore (str). The name is
            sanitized by save_load._sanitize_save_name. The file
            must exist in data/saves/{name}.db.

    Returns:
        sqlite3.Connection — a fresh connection to the restored DB,
        with PRAGMA foreign_keys = ON. The caller is responsible
        for closing the OLD connection before calling this.

    Raises:
        FileNotFoundError: if the backup file doesn't exist.
    """
    import save_load
    # save_load.load_game takes a save_name (not a path). The caller
    # may pass either — we extract the stem if it's a Path.
    from pathlib import Path
    if isinstance(filepath, Path):
        name = filepath.stem
    else:
        # If it's a path-like string, take the stem; otherwise treat
        # as a save name.
        p = Path(filepath)
        name = p.stem if (p.suffix or "/" in str(p) or "\\" in str(p)) else filepath
    return save_load.load_game(name)


# ----------------------------------------------------------------
# Generic record editors (defensive column validation)
# ----------------------------------------------------------------

def edit_fighter(conn, fighter_id, **kwargs):
    """Update any fighter field (defensive — validates column names).

    Accepts arbitrary keyword arguments and updates the corresponding
    columns on the fighters table for the given fighter_id. Keys
    that don't match any column on the fighters table are silently
    dropped (defensive — prevents typos from silently failing OR
    worse, writing to the wrong column).

    This is the SKELETON editor. A future task will add per-field
    validation (e.g., 'date_of_birth must be a valid ISO date',
    'current_promotion_id must reference an existing promotion').
    For now, the only validation is column-name existence.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the fighter to update.
        **kwargs: column_name → new_value pairs. Only keys that
            match actual columns on the fighters table are written.

    Returns:
        The number of fields actually updated (int). 0 if no valid
        columns were provided OR the fighter doesn't exist.
    """
    # Filter to valid columns only.
    valid_updates = _filter_valid_columns(conn, "fighters", kwargs)
    if not valid_updates:
        return 0

    # Verify the fighter exists.
    exists = conn.execute(
        "SELECT 1 FROM fighters WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    if not exists:
        return 0

    # Build the UPDATE statement.
    set_clause = ", ".join(f"{col}=?" for col in valid_updates)
    params = list(valid_updates.values()) + [fighter_id]
    conn.execute(
        f"UPDATE fighters SET {set_clause}, "
        "updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
        params,
    )

    # Refresh the descriptor snapshot (lazy import to avoid circular).
    try:
        from app import update_fighter_descriptor_snapshot
        update_fighter_descriptor_snapshot(conn, fighter_id)
    except ImportError:
        pass  # app.py not available (headless test?)

    return len(valid_updates)


def edit_promotion(conn, promotion_id, **kwargs):
    """Update any promotion field (defensive — validates column names).

    Same pattern as edit_fighter — accepts arbitrary kwargs, filters
    to valid columns on the promotions table, builds an UPDATE.

    Args:
        conn: sqlite3 connection (caller commits).
        promotion_id: the promotion to update.
        **kwargs: column_name → new_value pairs.

    Returns:
        The number of fields actually updated (int). 0 if no valid
        columns were provided OR the promotion doesn't exist.
    """
    valid_updates = _filter_valid_columns(conn, "promotions", kwargs)
    if not valid_updates:
        return 0

    exists = conn.execute(
        "SELECT 1 FROM promotions WHERE promotion_id=?",
        (promotion_id,),
    ).fetchone()
    if not exists:
        return 0

    set_clause = ", ".join(f"{col}=?" for col in valid_updates)
    params = list(valid_updates.values()) + [promotion_id]
    conn.execute(
        f"UPDATE promotions SET {set_clause}, "
        "updated_at=CURRENT_TIMESTAMP WHERE promotion_id=?",
        params,
    )
    return len(valid_updates)
