"""CAGE EMPIRE Player Settings (Stage 5 — Task Stage5-Final).

A simple key-value store for player preferences. Settings are stored
in the `player_settings` table (added in v3.7.0). The module is a
reader/writer — settings are read by other systems (news feed filter,
auto-save cadence, difficulty, voice descriptors toggle) at their
own cadence, NOT event-bus-driven.

CONVENTIONS compliance:
  §5  — One table-group per task. The `player_settings` table is the
        single group this task adds. The src/player_settings.py module
        is the reader AND the writer (dual role). Per §5.3, every new
        table must ship with both a writer and a reader — this module
        is both. Future UI panels + sim systems will read settings
        from this module.
  §6  — Smoke test protocol followed. The acceptance test rebuilds
        the DB, then exercises get_setting / set_setting /
        get_all_settings.
  §10 — Dynamic-version pattern. The acceptance test reads
        build_db.CODE_SCHEMA_VERSION at test time (no hardcoded
        version strings).
  §13 — Design Law: this is infrastructure that supports every
        pillar — the player's preferences shape how the sim presents
        itself (news volume, descriptor vs raw numbers, difficulty).
        The "Kingmaker" + "Empire Builder" + "Historian" fantasies
        are all filtered through the player's preference lens: a
        "hard" difficulty player experiences a more adversarial sim,
        a "verbose" news volume player sees more story texture, etc.
        The display_descriptors='true' default enforces §14 (the
        player sees descriptors, NOT raw numbers) — setting it to
        'false' is allowed for debugging but is a §14 violation in
        player-facing UI.
  §14 — Voice Layer: this module stores the display_descriptors
        setting (default 'true'). When 'true', every system that
        produces player-facing text routes through src/voice.py. The
        setting itself is internal (a key-value pair) — raw numbers
        are OK in the setting_value column (it's not player-facing
        text).
  §15 — Event Bus: NOT used. Settings are read by other systems at
        their own cadence — they are not transient events. The
        register_subscribers function is provided as a no-op for
        parity with the other system modules (called from App.__init__
        alongside the 12 other register_subscribers calls).

THE 6 DEFAULT SETTINGS (seeded by _migrate_v3_7_0_add_player_settings
AND by _build_fresh):
  news_filter_topics          = 'all'       (comma-separated topics
                                             or 'all' to show all)
  news_filter_min_importance  = '0'         (0=show all, 1=only
                                             important, 2=only major)
  news_volume                 = 'normal'    (verbose/normal/summary)
  auto_save_frequency         = '30'        (days between auto-saves)
  difficulty                  = 'normal'    (easy/normal/hard —
                                             affects starting cash,
                                             AI aggression, injury
                                             rates)
  display_descriptors         = 'true'      (show voice descriptors
                                             instead of raw numbers —
                                             should always be true
                                             per CONVENTIONS §14)

USAGE:
  from player_settings import get_setting, set_setting, get_all_settings

  # Read a setting (returns string, or default if not set).
  diff = get_setting(conn, 'difficulty', default='normal')
  if diff == 'hard':
      starting_cash = 250_000
  elif diff == 'easy':
      starting_cash = 1_000_000
  else:
      starting_cash = 500_000

  # Write a setting (upsert — INSERT OR REPLACE).
  set_setting(conn, 'news_volume', 'summary')

  # Read all settings (returns dict).
  all_prefs = get_all_settings(conn)
  # → {'difficulty': 'normal', 'news_volume': 'summary', ...}

  # register_subscribers is a no-op (settings are not event-driven)
  # but is called from App.__init__ for parity with other modules.
  from player_settings import register_subscribers
  register_subscribers()  # no-op

DESIGN DECISIONS:
  - Key-value store (not a typed-column table). Different settings
    have different types (string, int, bool, comma-list). A typed
    table would require an ALTER TABLE for every new setting. A
    key-value store lets us add settings without schema changes.
    Callers parse the string value per the setting's contract.
  - TEXT setting_value (not BLOB, not JSON). Each setting is a
    single value, not a nested object. Comma-separated lists use a
    plain string ('injury,title,upset'). JSON would be overkill.
  - updated_at timestamp on every write (for debugging — when did
    the player last change a setting?).
  - INSERT OR IGNORE in the migration seeds defaults idempotently
    (preserves user-modified values on a re-run).
  - register_subscribers is a no-op. The module is not event-driven.
    The function exists for parity with the other system modules so
    App.__init__ can call it alongside the 12 other register_
    subscribers calls without a special case.
"""

# ----------------------------------------------------------------
# Constants — the canonical list of known setting keys + their
# default values. Used by the migration to seed defaults AND by
# callers to validate keys (defensive — refuse to write unknown
# keys to prevent typos like 'difficulyt' instead of 'difficulty').
# ----------------------------------------------------------------

DEFAULT_SETTINGS = {
    "news_filter_topics":          "all",
    "news_filter_min_importance":  "0",
    "news_volume":                 "normal",
    "auto_save_frequency":         "30",
    "difficulty":                  "normal",
    "display_descriptors":         "true",
    # FIX-Critical (Issue 5): event name format the player prefers.
    # 'mixed' (default) = 70% numbered + 30% themed (backward compat).
    # 'numbered' = always "{Promo} {N}: {A} vs {B}".
    # 'themed'   = always "{Promo} {N}: {Theme}".
    "event_naming_style":          "mixed",
}


# ----------------------------------------------------------------
# Reader / writer
# ----------------------------------------------------------------

def get_setting(conn, key, default=None):
    """Read a single setting value.

    Args:
        conn: sqlite3 connection (read-only query).
        key: the setting_key to look up.
        default: returned if the setting is not in the table (None
            by default — callers should pass the canonical default
            from DEFAULT_SETTINGS if they want the seeded value).

    Returns:
        The setting_value (str), or `default` if the row doesn't
        exist. The caller is responsible for parsing the string
        (int, bool, comma-list) per the setting's contract.
    """
    try:
        row = conn.execute(
            "SELECT setting_value FROM player_settings "
            "WHERE setting_key=?",
            (key,),
        ).fetchone()
    except Exception:
        # Defensive — table doesn't exist (pre-migration DB?) or
        # other DB error. Return the default.
        return default
    if row is None:
        return default
    return row[0]


def set_setting(conn, key, value):
    """Write a single setting value (upsert).

    Defensive — refuses to write unknown keys (keys not in
    DEFAULT_SETTINGS). This catches typos like 'difficulyt' instead
    of 'difficulty' at write time, preventing silent corruption. If
    a future task needs to add a new setting, it must add the key
    to DEFAULT_SETTINGS first.

    Args:
        conn: sqlite3 connection (caller commits).
        key: the setting_key to write. Must be in DEFAULT_SETTINGS.
        value: the setting_value. Coerced to str (so callers can
            pass int/bool without manual conversion — 30 → '30',
            True → 'True', etc.).

    Returns:
        True if the setting was written, False if the key was
        rejected (not in DEFAULT_SETTINGS).
    """
    if key not in DEFAULT_SETTINGS:
        return False
    # Coerce to string — SQLite stores TEXT, but Python callers may
    # pass int (30) or bool (True). str(30) = '30', str(True) =
    # 'True'. The display_descriptors setting uses 'true'/'false'
    # (lowercase) per the brief — callers should pass the correct
    # string. For booleans, use 'true'/'false' explicitly.
    if isinstance(value, bool):
        # Convert Python bool to lowercase string ('true'/'false').
        value_str = 'true' if value else 'false'
    else:
        value_str = str(value)
    conn.execute(
        "INSERT OR REPLACE INTO player_settings "
        "(setting_key, setting_value, updated_at) "
        "VALUES (?, ?, CURRENT_TIMESTAMP)",
        (key, value_str),
    )
    return True


def get_all_settings(conn):
    """Return a dict of all settings (key → value).

    Missing settings (not yet seeded) fall back to their default
    from DEFAULT_SETTINGS. This means callers always see the full
    set of known settings even on a partially-seeded DB.

    Args:
        conn: sqlite3 connection.

    Returns:
        Dict of {setting_key: setting_value}. Includes every key
        in DEFAULT_SETTINGS (with the seeded value if present, the
        default value if not). May include additional keys if the
        table has rows not in DEFAULT_SETTINGS (forward-compat —
        a newer codebase added a setting this codebase doesn't know
        about; we surface it verbatim rather than dropping it).
    """
    settings = dict(DEFAULT_SETTINGS)  # start with defaults
    try:
        rows = conn.execute(
            "SELECT setting_key, setting_value FROM player_settings"
        ).fetchall()
    except Exception:
        # Defensive — table doesn't exist. Return defaults.
        return settings
    for key, value in rows:
        settings[key] = value
    return settings


# ----------------------------------------------------------------
# Registration (no-op — settings are not event-driven)
# ----------------------------------------------------------------

def register_subscribers():
    """No-op. Settings are read by other systems at their own cadence,
    not event-bus-driven. This function exists for parity with the
    other system modules (news, social, rivalries, etc.) so App.
    __init__ can call it alongside the other register_subscribers
    calls without a special case.

    Subscribes to: nothing.
    """
    return None
