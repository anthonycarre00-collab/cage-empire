import sqlite3
import random
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

def fighter_name(conn, fighter_id):
    row = conn.execute("SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id=?", (fighter_id,)).fetchone()
    return row[0] if row else "Unknown"

def get_clock(conn):
    return conn.execute("SELECT current_date, current_day, current_week, current_month, current_year, tick_counter FROM simulation_clock WHERE clock_id=1").fetchone()

def advance_day(conn):
    row = get_clock(conn)
    dt = datetime.strptime(row[0], "%Y-%m-%d") + timedelta(days=1)
    day = row[1] + 1
    week = ((day - 1) // 7) + 1
    conn.execute(
        "UPDATE simulation_clock SET current_date=?, current_day=?, current_week=?, current_month=?, current_year=?, current_tick_type='day', tick_counter=tick_counter+1, updated_at=CURRENT_TIMESTAMP WHERE clock_id=1",
        (dt.strftime("%Y-%m-%d"), day, week, dt.month, dt.year),
    )

def write_news(conn, headline, body, topic="event", event_id=None, fight_id=None, fighter_id=None, promotion_id=None):
    src = conn.execute("SELECT news_source_id FROM news_sources WHERE name='System Feed'").fetchone()
    src_id = src[0] if src else conn.execute("INSERT INTO news_sources (name, credibility, sensationalism, bias, regional_reach, reliability, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)", ("System Feed", 70, 40, 50, 60, 80, 80)).lastrowid
    conn.execute("INSERT INTO news_items (news_source_id, headline, body, sentiment, topic, event_id, fight_id, fighter_id, promotion_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (src_id, headline, body, "neutral", topic, event_id, fight_id, fighter_id, promotion_id))

def write_commentary(conn, event_id=None, fight_id=None, text=""):
    speaker = conn.execute("SELECT staff_id FROM staff WHERE role_type='commentator' LIMIT 1").fetchone()
    speaker_id = speaker[0] if speaker else None
    conn.execute("INSERT INTO commentary_segments (event_id, fight_id, segment_type, speaker_staff_id, text, importance) VALUES (?, ?, ?, ?, ?, ?)", (event_id, fight_id, "play_by_play", speaker_id, text, 70))


# ----------------------------------------------------------------
# Fighter roster display helper (Task ID 6).
#
# Extracted from the inline query that used to live in
# `App.refresh_all()` so the multi-promotion filter logic is
# testable without a Tkinter display. The test script
# `scripts/test_promotion_filter.py` imports this helper directly.
#
# Returns the same 4-tuple shape the Fighters Treeview was already
# rendering: (name, weight_class, promotion_name, record) — so
# `refresh_all()`'s `insert('', 'end', values=r)` call is unchanged.
#
# Schema version is unchanged (still 1.3.0) — no new tables, no new
# columns. RFL stays inert (no AI behaviour); this helper just makes
# the UI aware that multiple promotions exist.
# ----------------------------------------------------------------

def get_fighters_for_display(conn, promotion_filter=None):
    """Return fighter rows for the UI Fighters tree.

    Args:
        conn: sqlite3 connection.
        promotion_filter: None (all fighters, including free agents
            with current_promotion_id = NULL), or a promotion_id int
            (only fighters whose current_promotion_id matches).

    Returns:
        List of 4-tuples: (name, weight_class, promotion_name, record).
        - name:            fighters.first_name || ' ' || fighters.last_name
        - weight_class:    weight_classes.name, or 'Unknown' if no WC
        - promotion_name:  promotions.name, or 'Unassigned' if no
                           current promotion (i.e. a free agent)
        - record:          'W-L-D' string from fighter_career counters,
                           defaulting to '0-0-0' if no career row yet
    """
    sql = (
        "SELECT f.first_name || ' ' || f.last_name, "
        "COALESCE(w.name, 'Unknown'), "
        "COALESCE(p.name, 'Unassigned'), "
        "COALESCE(fc.record_wins, 0) || '-' || COALESCE(fc.record_losses, 0) || '-' || COALESCE(fc.record_draws, 0) "
        "FROM fighters f "
        "LEFT JOIN weight_classes w ON w.weight_class_id = f.weight_class_id "
        "LEFT JOIN promotions p ON p.promotion_id = f.current_promotion_id "
        "LEFT JOIN fighter_career fc ON fc.fighter_id = f.fighter_id"
    )
    if promotion_filter is not None:
        sql += " WHERE f.current_promotion_id = ?"
        sql += " ORDER BY f.fighter_id"
        return conn.execute(sql, (promotion_filter,)).fetchall()
    sql += " ORDER BY f.fighter_id"
    return conn.execute(sql).fetchall()

# ----------------------------------------------------------------
# Real attribute-based fight resolver (Task ID 3).
#
# Replaces the original coin-flip resolve_next_fight() with a
# probabilistic model that reads fighter_attributes (punch_power,
# cardio, fight_iq, chin) and fighter_personality (aggression,
# composure, morale) for both fighters, computes a noisy power
# score per fighter, and derives winner / result_type / finish_round
# / finish_time / performance_rating / fan_reaction_rating from the
# margin. See docs/STAGES.md Task ID 3 for the spec. Schema version
# is unchanged (still 1.2.1) — no new tables, no new columns.
# ----------------------------------------------------------------

# Defensive defaults used only if a fighter_attributes or
# fighter_personality row is somehow missing. The seed always
# inserts both, so these are belt-and-braces.
_DEFAULT_ATTRS = (50, 50, 50, 50)  # punch_power, cardio, fight_iq, chin
_DEFAULT_PERS = (50, 50, 50)       # aggression, composure, morale

# Base Gaussian noise sigma applied to each fighter's adjusted power
# score. Spec says "sigma ~= 15". Per-fighter sigma is then narrowed
# or widened by the consistency modifier (see _consistency_sigma).
_BASE_SIGMA = 15.0


def _load_fighter_stats(conn, fighter_id):
    """Load one fighter's combat attributes + personality for the resolver.

    Returns a flat dict with all 7 fields. Falls back to defaults (50s)
    if either row is missing — defensive, the seed always inserts both.
    """
    attrs = conn.execute(
        "SELECT punch_power, cardio, fight_iq, chin FROM fighter_attributes WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    pers = conn.execute(
        "SELECT aggression, composure, morale FROM fighter_personality WHERE fighter_id=?",
        (fighter_id,),
    ).fetchone()
    a = attrs if attrs else _DEFAULT_ATTRS
    p = pers if pers else _DEFAULT_PERS
    return {
        "punch_power": a[0], "cardio": a[1], "fight_iq": a[2], "chin": a[3],
        "aggression": p[0], "composure": p[1], "morale": p[2],
    }


def _power_score(stats):
    """Weighted blend of the 4 combat attributes. Range ~0-100.

    punch_power * 0.4 + cardio * 0.3 + fight_iq * 0.2 + chin * 0.1
    (per the Task ID 3 spec).
    """
    return (
        stats["punch_power"] * 0.4
        + stats["cardio"] * 0.3
        + stats["fight_iq"] * 0.2
        + stats["chin"] * 0.1
    )


def _consistency_sigma(stats):
    """Composure narrows variance. Returns adjusted sigma in [7.5, 22.5].

    Spec: multiply base sigma by `1 - (composure - 50) / 200`, clamped
    to [0.5, 1.5]. So composure=90 -> sigma * 0.8, composure=10 ->
    sigma * 1.2.
    """
    mod = 1.0 - (stats["composure"] - 50) / 200.0
    mod = max(0.5, min(1.5, mod))
    return _BASE_SIGMA * mod


def _morale_multiplier(stats):
    """Morale scales power up/down. Range [0.85, 1.15] for morale in [0, 100].

    Spec: `0.85 + (morale / 100) * 0.30`. So morale=50 -> x1.00,
    morale=0 -> x0.85, morale=100 -> x1.15.
    """
    return 0.85 + (stats["morale"] / 100.0) * 0.30


def _pick_finish_type(winner_stats, loser_stats):
    """Pick `ko_tko` vs `submission` for a finish outcome.

    Weighted by the winner's punch_power (KO bias) vs fight_iq
    (submission bias). The loser's chin affects the *probability of a
    finish* (captured by the margin), not the split between finish
    types, so it is intentionally not used here. This keeps the
    result_type distribution varied across fighter styles — a pure
    puncher KOs, a tactician submits — which is needed to satisfy the
    acceptance test's "no single result_type > 60%" assertion in the
    symmetric all-90-vs-all-30 matchup. See worklog D1.
    """
    ko_weight = max(1, winner_stats["punch_power"])
    sub_weight = max(1, winner_stats["fight_iq"])
    return "ko_tko" if random.random() < ko_weight / (ko_weight + sub_weight) else "submission"


def _format_finish_time():
    """Random finish time within a 5-minute round. Returns 'M:SS' in [0:01, 4:59]."""
    total = random.randint(1, 299)
    return f"{total // 60}:{total % 60:02d}"


def _resolve_outcome(stats_a, stats_b, scheduled_rounds):
    """Resolve the probabilistic outcome of a fight between two fighters.

    Pure function (no DB writes, no I/O) so the test script can call it
    directly to verify distribution properties without going through the
    database. Returns a dict with: winner ('a' or 'b'), abs_margin,
    result_type, finish_round, finish_time, performance_rating,
    fan_reaction_rating, winner_base, loser_base.
    """
    base_a = _power_score(stats_a)
    base_b = _power_score(stats_b)

    # Morale scales power up/down. Composure scales noise sigma.
    adj_a = base_a * _morale_multiplier(stats_a)
    adj_b = base_b * _morale_multiplier(stats_b)

    sigma_a = _consistency_sigma(stats_a)
    sigma_b = _consistency_sigma(stats_b)

    # Sample a noisy score per fighter. random.gauss(mu, sigma) — here
    # mu=0 and we add the noise to the adjusted score. random.gauss is
    # used (not random.randint) per the spec and the acceptance checklist.
    noisy_a = adj_a + random.gauss(0, sigma_a)
    noisy_b = adj_b + random.gauss(0, sigma_b)

    signed_margin = noisy_a - noisy_b
    if signed_margin >= 0:
        winner = "a"
        winner_stats, loser_stats = stats_a, stats_b
        winner_base, loser_base = base_a, base_b
    else:
        winner = "b"
        winner_stats, loser_stats = stats_b, stats_a
        winner_base, loser_base = base_b, base_a
    abs_margin = abs(signed_margin)

    # Decide result_type from margin per the Task ID 3 spec.
    #   margin > 30  -> finish (early, round 1-2)
    #   margin 15-30 -> finish (mid, round 2-3)
    #   margin 5-15  -> unanimous_decision
    #   margin < 5   -> coin flip split_decision / draw
    # The spec maps margin > 30 definitively to ko_tko. We deviate
    # slightly (see worklog D1): at any finish margin we let both
    # ko_tko and submission be possible, weighted by the winner's
    # style. This is required to pass the acceptance test's
    # "no single result_type > 60%" assertion in the all-90-vs-all-30
    # matchup (where abs_margin > 30 occurs ~99% of the time).
    if abs_margin >= 15:
        result_type = _pick_finish_type(winner_stats, loser_stats)
        if abs_margin > 30:
            # Early finish — rounds 1-2.
            finish_round = random.randint(1, 2)
        else:
            # Mid finish — rounds 2-3.
            finish_round = random.randint(2, 3)
        # Aggression differential shifts the finish round (spec §6).
        # More aggressive winner finishes earlier; less aggressive
        # winner lets the loser survive a round longer.
        aggr_diff = winner_stats["aggression"] - loser_stats["aggression"]
        if aggr_diff >= 20:
            finish_round = max(1, finish_round - 1)
        elif aggr_diff <= -20:
            finish_round = min(scheduled_rounds, finish_round + 1)
        finish_time = _format_finish_time()
    elif abs_margin >= 5:
        result_type = "unanimous_decision"
        finish_round = scheduled_rounds
        finish_time = "5:00"
    else:
        # Coin flip per spec for the sub-5 case.
        result_type = random.choice(["split_decision", "draw"])
        finish_round = scheduled_rounds
        finish_time = "5:00"

    # Performance rating: bigger margin -> higher. Clamp 60-95.
    performance_rating = max(60, min(95, int(round(60 + abs_margin))))

    # Fan reaction: lower base, KO bonus, upset bonus. Clamp 60-95.
    # KO/TKO is +10 vs decision (more exciting). Upset (loser had a
    # higher base power score than winner) is +5 (fans love an upset).
    fan = 65 + int(abs_margin * 0.5)
    if result_type == "ko_tko":
        fan += 10
    if loser_base > winner_base:
        fan += 5
    fan_reaction_rating = max(60, min(95, fan))

    return {
        "winner": winner,
        "abs_margin": abs_margin,
        "result_type": result_type,
        "finish_round": finish_round,
        "finish_time": finish_time,
        "performance_rating": performance_rating,
        "fan_reaction_rating": fan_reaction_rating,
        "winner_base": winner_base,
        "loser_base": loser_base,
    }


def _format_fight_news(winner_name, loser_name, result_type, finish_round):
    """Build (headline, body) for a non-draw fight result.

    Enriches the original "X defeats Y" template with the result type
    and finish round. The write_news() call itself is unchanged.
    """
    pretty = result_type.replace("_", " ")
    if result_type == "ko_tko":
        headline = f"{winner_name} KO's {loser_name} in round {finish_round}"
        body = f"{winner_name} stopped {loser_name} by {pretty} in round {finish_round}."
    elif result_type == "submission":
        headline = f"{winner_name} submits {loser_name} in round {finish_round}"
        body = f"{winner_name} tapped out {loser_name} by submission in round {finish_round}."
    elif result_type == "unanimous_decision":
        headline = f"{winner_name} beats {loser_name} by unanimous decision"
        body = f"{winner_name} defeated {loser_name} by unanimous decision after {finish_round} rounds."
    elif result_type == "split_decision":
        headline = f"{winner_name} edges {loser_name} by split decision"
        body = f"{winner_name} took a split decision over {loser_name} after {finish_round} rounds."
    else:
        headline = f"{winner_name} defeats {loser_name}"
        body = f"{winner_name} beat {loser_name} by {pretty}."
    return headline, body


def _format_fight_commentary(winner_name, loser_name, result_type, finish_round):
    """Build a short commentary line for a non-draw fight result."""
    if result_type == "ko_tko":
        return f"{winner_name} puts {loser_name} away by KO/TKO in round {finish_round}."
    if result_type == "submission":
        return f"{winner_name} forces the tap from {loser_name} in round {finish_round}."
    if result_type == "unanimous_decision":
        return f"All three judges score it for {winner_name} over {loser_name}."
    if result_type == "split_decision":
        return f"Split scorecards — {winner_name} takes the nod over {loser_name}."
    return f"{winner_name} has just defeated {loser_name}."


def resolve_next_fight(conn):
    """Resolve the next scheduled fight using the attribute-based model.

    Picks the lowest-fight_id unresolved fight, loads both fighters'
    stats, runs the probabilistic resolver, persists the result, updates
    career counters, and writes a news item + commentary segment.
    Returns the resolved fight_id (or None if no unresolved fight was
    found). The function does not call conn.commit() itself — the caller
    commits, matching the original signature and the UI's on_resolve_fight
    callsite.

    Side effects (preserved from the original coin-flip version):
      - UPDATE fights SET winner/loser/result_type/finish_round/...
      - UPDATE fight_participants SET is_winner=...
      - UPDATE fighter_career SET record_wins/losses/draws, streaks
      - INSERT INTO fight_history (2 rows, one per fighter)  [v1.3.0]
      - write_news(...)  (enriched headline + body, same signature)
      - write_commentary(...)  (enriched text, same signature)
    """
    fight = conn.execute(
        "SELECT f.fight_id, f.event_id, f.scheduled_rounds, e.promotion_id, "
        "f.weight_class_id, e.event_date "
        "FROM fights f JOIN events e ON e.event_id=f.event_id "
        "WHERE f.winner_fighter_id IS NULL AND f.result_type IS NULL "
        "ORDER BY f.fight_id LIMIT 1"
    ).fetchone()
    if not fight:
        return None
    fight_id, event_id, scheduled_rounds, promo_id, weight_class_id, event_date = fight
    parts = conn.execute(
        "SELECT fighter_id FROM fight_participants WHERE fight_id=? ORDER BY corner",
        (fight_id,),
    ).fetchall()
    if len(parts) < 2:
        return None
    a_id, b_id = parts[0][0], parts[1][0]

    stats_a = _load_fighter_stats(conn, a_id)
    stats_b = _load_fighter_stats(conn, b_id)
    outcome = _resolve_outcome(stats_a, stats_b, scheduled_rounds)

    result_type = outcome["result_type"]
    finish_round = outcome["finish_round"]
    finish_time = outcome["finish_time"]
    performance_rating = outcome["performance_rating"]
    fan_reaction_rating = outcome["fan_reaction_rating"]

    a_name = fighter_name(conn, a_id)
    b_name = fighter_name(conn, b_id)

    if result_type == "draw":
        # Draw: no winner/loser. Both participants get a draw on their
        # record. Streaks are unchanged (a draw neither extends nor
        # breaks a streak in most MMA rulesets).
        conn.execute(
            "UPDATE fights SET winner_fighter_id=NULL, loser_fighter_id=NULL, "
            "result_type=?, finish_round=?, finish_time=?, "
            "performance_rating=?, fan_reaction_rating=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fight_id=?",
            (result_type, finish_round, finish_time,
             performance_rating, fan_reaction_rating, fight_id),
        )
        conn.execute(
            "UPDATE fight_participants SET is_winner=0 WHERE fight_id=?",
            (fight_id,),
        )
        conn.execute(
            "UPDATE fighter_career SET record_draws=record_draws+1, "
            "updated_at=CURRENT_TIMESTAMP WHERE fighter_id IN (?, ?)",
            (a_id, b_id),
        )
        headline = f"{a_name} and {b_name} fight to a draw"
        body = f"{a_name} and {b_name} fought to a draw after {finish_round} rounds."
        commentary = f"The judges cannot split {a_name} and {b_name} — it's a draw."
        news_fighter_id = None
    else:
        if outcome["winner"] == "a":
            winner_id, loser_id = a_id, b_id
            winner_name, loser_name = a_name, b_name
        else:
            winner_id, loser_id = b_id, a_id
            winner_name, loser_name = b_name, a_name
        conn.execute(
            "UPDATE fights SET winner_fighter_id=?, loser_fighter_id=?, result_type=?, "
            "finish_round=?, finish_time=?, performance_rating=?, fan_reaction_rating=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE fight_id=?",
            (winner_id, loser_id, result_type, finish_round, finish_time,
             performance_rating, fan_reaction_rating, fight_id),
        )
        conn.execute(
            "UPDATE fight_participants SET is_winner=CASE WHEN fighter_id=? THEN 1 ELSE 0 END "
            "WHERE fight_id=?",
            (winner_id, fight_id),
        )
        conn.execute(
            "UPDATE fighter_career SET record_wins=record_wins+1, win_streak=win_streak+1, "
            "loss_streak=0, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (winner_id,),
        )
        conn.execute(
            "UPDATE fighter_career SET record_losses=record_losses+1, loss_streak=loss_streak+1, "
            "win_streak=0, updated_at=CURRENT_TIMESTAMP WHERE fighter_id=?",
            (loser_id,),
        )
        headline, body = _format_fight_news(winner_name, loser_name, result_type, finish_round)
        commentary = _format_fight_commentary(winner_name, loser_name, result_type, finish_round)
        news_fighter_id = winner_id

    # ----------------------------------------------------------------
    # Write two rows to `fight_history` (one per fighter, from their
    # perspective). New in v1.3.0 (Task ID 4) — separate from the
    # mutable `fighter_career` counters. The UNIQUE (fight_id, fighter_id)
    # constraint enforces one row per fighter per fight. `title_at_stake`
    # is hardcoded to 0 for now; Task ID 11 (titles) will populate it.
    # `score_margin` is the rounded absolute margin from the resolver.
    # Read by upcoming rankings, legacy, and stats-based commentary
    # work (Tasks 10, 11, 14, 19, 23) — see docs/STAGES.md Task ID 4.
    #
    # Defensive DELETE: in normal gameplay each fight is resolved exactly
    # once, so there are no prior fight_history rows to conflict with.
    # But tests (and any future "re-resolve" feature) may reset the
    # fights row and call resolve_next_fight() again on the same
    # fight_id. Without this DELETE, the INSERT below would crash on
    # the UNIQUE constraint. Clearing prior rows makes the resolver
    # idempotent for re-resolution — the latest result wins, which is
    # the sensible behaviour. (This is what keeps
    # scripts/test_fight_resolver.py passing after Task ID 4.)
    # ----------------------------------------------------------------
    conn.execute(
        "DELETE FROM fight_history WHERE fight_id=?",
        (fight_id,),
    )
    score_margin_int = int(round(outcome["abs_margin"]))
    if result_type == "draw":
        # Both fighters get a 'draw' row, opponent_id = the other fighter.
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'draw', ?, ?, ?, ?, ?, ?, ?, 0)",
            (fight_id, a_id, b_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id),
        )
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'draw', ?, ?, ?, ?, ?, ?, ?, 0)",
            (fight_id, b_id, a_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id),
        )
    else:
        # Winner row: outcome='win', opponent_id = loser.
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'win', ?, ?, ?, ?, ?, ?, ?, 0)",
            (fight_id, winner_id, loser_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id),
        )
        # Loser row: outcome='loss', opponent_id = winner.
        conn.execute(
            "INSERT INTO fight_history (fight_id, fighter_id, opponent_id, "
            "outcome, result_type, finish_round, finish_time, score_margin, "
            "event_id, event_date, weight_class_id, title_at_stake) "
            "VALUES (?, ?, ?, 'loss', ?, ?, ?, ?, ?, ?, ?, 0)",
            (fight_id, loser_id, winner_id, result_type, finish_round, finish_time,
             score_margin_int, event_id, event_date, weight_class_id),
        )

    # The write_news / write_commentary calls themselves are preserved
    # exactly — only the headline / body / commentary strings change.
    write_news(conn, headline, body, "fight", event_id, fight_id, news_fighter_id, promo_id)
    write_commentary(conn, event_id, fight_id, commentary)
    return fight_id

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MMA Booking Sim")
        self.geometry("1280x760")
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        # Promotion filter state (Task ID 6). None = all promotions
        # (including free agents with current_promotion_id = NULL);
        # an int = restrict the Fighters tree to that promotion_id.
        # Default is "All Promotions" so the UI opens showing every
        # fighter across every promotion.
        self.current_promotion_filter = None
        # Parallel list mapping the combobox's selected index to a
        # promotion_id (or None for the "All Promotions" sentinel).
        # Populated by refresh_all() alongside the combobox values.
        self._promo_filter_ids = [None]
        self.build_ui()
        self.refresh_all()

    def build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill='x')
        ttk.Button(top, text="Advance Day", command=self.on_advance_day).pack(side='left', padx=4)
        ttk.Button(top, text="Resolve Fight", command=self.on_resolve_fight).pack(side='left', padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side='left', padx=4)

        # Promotion filter (Task ID 6) — lets the player focus the
        # Fighters tree on one promotion's roster. None = all
        # promotions. Defaults to "All Promotions". The dropdown
        # values are refreshed from the DB on every refresh_all() call
        # so promotions added by future tasks (or removed via free-
        # agency, Task ID 13) are reflected automatically. The
        # current selection is preserved across refreshes if the
        # promotion still exists; otherwise it resets to "All".
        ttk.Label(top, text="Filter:").pack(side='left', padx=(12, 4))
        self.promo_filter_var = tk.StringVar()
        self.promo_filter_combo = ttk.Combobox(
            top, textvariable=self.promo_filter_var, state='readonly',
            width=22, values=["All Promotions"]
        )
        self.promo_filter_combo.current(0)
        # <<ComboboxSelected>> only fires on user interaction, not on
        # programmatic .set()/.current() calls — so calling refresh_all()
        # from inside the handler (which re-populates the combobox)
        # does NOT cause infinite recursion. Verified empirically by
        # the smoke test.
        self.promo_filter_combo.bind("<<ComboboxSelected>>", self.on_promo_filter_change)
        self.promo_filter_combo.pack(side='left', padx=4)

        self.clock_var = tk.StringVar()
        ttk.Label(top, textvariable=self.clock_var, font=("Segoe UI", 11, "bold")).pack(side='right')

        main = ttk.Panedwindow(self, orient='horizontal')
        main.pack(fill='both', expand=True, padx=8, pady=8)

        left = ttk.Frame(main, padding=6)
        center = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=2)
        main.add(center, weight=2)
        main.add(right, weight=2)

        ttk.Label(left, text="Fighters", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fighters = ttk.Treeview(left, columns=('name','wc','promo','record'), show='headings', height=16)
        for c,w in [('name',170),('wc',110),('promo',140),('record',100)]:
            self.fighters.heading(c, text=c.title())
            self.fighters.column(c, width=w, anchor='w')
        self.fighters.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(center, text="Events", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.events = ttk.Treeview(center, columns=('date','name','status'), show='headings', height=8)
        for c,w in [('date',110),('name',250),('status',120)]:
            self.events.heading(c, text=c.title())
            self.events.column(c, width=w, anchor='w')
        self.events.pack(fill='x', pady=(6,10))

        ttk.Label(center, text="Fights", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.fights = ttk.Treeview(center, columns=('id','matchup','wc','result'), show='headings', height=10)
        for c,w in [('id',60),('matchup',260),('wc',110),('result',120)]:
            self.fights.heading(c, text=c.title())
            self.fights.column(c, width=w, anchor='w')
        self.fights.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(right, text="News", font=("Segoe UI", 11, "bold")).pack(anchor='w')
        self.news = tk.Listbox(right, height=18)
        self.news.pack(fill='both', expand=True, pady=(6,0))

        ttk.Label(right, text="Commentary", font=("Segoe UI", 11, "bold")).pack(anchor='w', pady=(10,0))
        self.commentary = tk.Listbox(right, height=8)
        self.commentary.pack(fill='both', expand=True, pady=(6,0))

    def clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def refresh_all(self):
        row = get_clock(self.conn)
        self.clock_var.set(f"{row[0]} | Day {row[1]} | Week {row[2]} | Month {row[3]} | Year {row[4]} | Ticks {row[5]}")

        # ----------------------------------------------------------------
        # Refresh promotion filter dropdown from DB (Task ID 6).
        # Promotions may be added by future tasks (e.g. scout-driven
        # expansion) or removed (fighters become free agents, Task ID
        # 13). The dropdown is rebuilt on every refresh so it always
        # reflects the current DB state. The user's current selection
        # is preserved if the promotion still exists; otherwise the
        # filter resets to "All Promotions" so the UI never ends up
        # pointing at a deleted promotion_id.
        # ----------------------------------------------------------------
        current_selection = self.promo_filter_var.get() or "All Promotions"
        promo_names = ["All Promotions"]
        promo_ids = [None]  # parallel list: None for "All", else promotion_id
        for pid, pname in self.conn.execute(
            "SELECT promotion_id, name FROM promotions ORDER BY promotion_id"
        ):
            promo_names.append(pname)
            promo_ids.append(pid)
        self.promo_filter_combo['values'] = promo_names
        if current_selection in promo_names:
            # Re-select the same promotion the user had picked.
            # .set() does NOT fire <<ComboboxSelected>> (Tkinter only
            # fires that on user interaction), so no recursion here.
            self.promo_filter_combo.set(current_selection)
        else:
            self.promo_filter_combo.current(0)
            self.current_promotion_filter = None
        # Store the parallel id list so on_promo_filter_change can map
        # the combobox's selected index -> promotion_id.
        self._promo_filter_ids = promo_ids

        self.clear_tree(self.fighters)
        self.clear_tree(self.events)
        self.clear_tree(self.fights)
        self.news.delete(0, tk.END)
        self.commentary.delete(0, tk.END)

        for r in get_fighters_for_display(self.conn, self.current_promotion_filter):
            self.fighters.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT event_date, event_name, status FROM events ORDER BY event_date"):
            self.events.insert('', 'end', values=r)

        for r in self.conn.execute("""
            SELECT f.fight_id,
                   COALESCE(a.first_name || ' ' || a.last_name, 'TBD') || ' vs ' || COALESCE(b.first_name || ' ' || b.last_name, 'TBD'),
                   COALESCE(w.name, 'Unknown'),
                   COALESCE(f.result_type, 'pending')
            FROM fights f
            LEFT JOIN fight_participants pa ON pa.fight_id=f.fight_id AND pa.corner='red'
            LEFT JOIN fight_participants pb ON pb.fight_id=f.fight_id AND pb.corner='blue'
            LEFT JOIN fighters a ON a.fighter_id=pa.fighter_id
            LEFT JOIN fighters b ON b.fighter_id=pb.fighter_id
            LEFT JOIN weight_classes w ON w.weight_class_id=f.weight_class_id
            ORDER BY f.fight_id
        """):
            self.fights.insert('', 'end', values=r)

        for r in self.conn.execute("SELECT headline FROM news_items ORDER BY news_item_id DESC LIMIT 10"):
            self.news.insert(tk.END, r[0])
        for r in self.conn.execute("SELECT text FROM commentary_segments ORDER BY commentary_segment_id DESC LIMIT 10"):
            self.commentary.insert(tk.END, r[0])

    def on_promo_filter_change(self, event=None):
        """Handle promotion filter dropdown change (Task ID 6).

        Reads the combobox's currently selected index, looks up the
        corresponding promotion_id in the parallel `_promo_filter_ids`
        list (set by `refresh_all()` when the dropdown was last
        populated), stores it in `current_promotion_filter`, and
        triggers a full refresh — which re-runs the fighter query
        through `get_fighters_for_display` with the new filter applied.

        Index 0 is always "All Promotions" -> filter = None. Any
        other index maps to a promotion_id int.

        Note: `refresh_all()` re-populates the combobox as a side
        effect, but `<<ComboboxSelected>>` only fires on user
        interaction (not on programmatic `.set()`), so there is no
        infinite recursion here.
        """
        idx = self.promo_filter_combo.current()
        if idx <= 0:
            self.current_promotion_filter = None
        else:
            # Defensive: bounds-check against the parallel list. If
            # the combobox is somehow out of sync with the list (e.g.
            # refresh hasn't run yet), fall back to "All Promotions".
            if 0 <= idx < len(self._promo_filter_ids):
                self.current_promotion_filter = self._promo_filter_ids[idx]
            else:
                self.current_promotion_filter = None
        self.refresh_all()

    def on_advance_day(self):
        try:
            advance_day(self.conn)
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

    def on_resolve_fight(self):
        try:
            if resolve_next_fight(self.conn) is None:
                messagebox.showinfo("Resolve Fight", "No unresolved fights found.")
            self.conn.commit()
            self.refresh_all()
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    App().mainloop()
