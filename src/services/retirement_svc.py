"""CAGE EMPIRE retirement service (Stage 6 — Task 6.0).

Extracted from src/app.py + src/services/fight_engine.py (2 functions
+ 1 thin wrapper, ~700 lines including docstrings):
  - generate_fighter              (was app.py:635 — ~550 lines, called by
                                   tick_processor._check_retirements +
                                   agent_offers + 3 tests)
  - _vacate_title_on_retirement   (was app.py:2815 — moved to
                                   fight_engine.py in Step 3 of Task 6.0,
                                   now physically moved here per Step 5
                                   of the brief. Called by
                                   tick_processor._check_retirements.)
  - check_retirements (wrapper)   (thin wrapper delegating to
                                   tick_processor._check_retirements)

CONVENTIONS compliance:
  §5  — One table-group per task. This module does NOT add tables;
        it reads/writes the existing `fighters`, `fighter_attributes`,
        `fighter_personality`, `fighter_career`, `fighter_bios`,
        `name_pools`, `style_archetypes`, `personality_archetypes`,
        `weight_classes`, `gyms`, `nations`, `cities`, `news_items`,
        `news_sources`, `titles`, `promotions`, and `regen_lineage`
        tables only.
  §6  — Smoke test protocol followed. All 38 acceptance tests pass
        after extraction.
  §13 — Design Law: this is the Growth pillar — retirements create
        space for new prospects (the torch-passing story). The
        replacement fighter inherits the retiring champion's style
        archetype 30% of the time (D3 in app.py comment below).
  §14 — Voice Layer: N/A for the function bodies (no player-facing
        attribute text). The news headlines written by these
        functions use direct fighter names, not voice descriptors.
  §15 — Event Bus: generate_fighter publishes Events.FIGHTER_GENERATED
        inline (Phase A5 behaviour, preserved verbatim).
        _vacate_title_on_retirement writes a 'retirement' news item
        inline (preserved verbatim). check_retirements is a thin
        wrapper around tick_processor._check_retirements, which
        publishes Events.FIGHTER_RETIRED inline.

Migration impact: NONE (code-only refactor).
"""
import random
from datetime import datetime, timedelta


# ----------------------------------------------------------------
# Regen engine (Task ID 14).
#
# When a fighter retires (Task 12), the roster shrinks by one. Without
# regen, the roster eventually empties as fighters age out — breaking
# the "playable forever" loop. generate_fighter() creates a replacement
# fighter from the name pools with a similar style DNA (same
# fight_style_archetype_id as the retiring fighter). The new fighter
# enters as a FREE AGENT (current_promotion_id=NULL, is_active=1,
# is_retired=0) so they appear in Task 13's Free Agents tab and can be
# signed by any promotion.
#
# Called from tick_processor._check_retirements() for each retiring
# fighter. The caller records the regen_lineage row linking the
# retiring fighter to the replacement.
#
# Design choices (documented for future maintainers):
#   D1. No `used_names` table — uniqueness is checked against the
#       existing `fighters` table (first_name + last_name combination).
#       This is simpler than maintaining a separate registry and stays
#       correct when fighters are deleted (their names become available
#       again). See build_db.py's name_pools schema comment.
#   D2. No rankings row at generation time — the new fighter is a free
#       agent with no promotion, and the rankings table requires a
#       promotion_id (NOT NULL). When the player or AI signs them via
#       Task 13's sign_free_agent, the next fight resolution will call
#       _update_rankings_after_resolution which uses _get_or_create_ranking_row
#       to create the rankings row defensively on the fly.
#   D3. No memory resurfacing yet — the fighter_memory_links table
#       exists but is NOT populated by this function. Memory resurfacing
#       (style echoes, gym heirs, regional rivals, successors) is a
#       future enhancement. This task just generates a fresh fighter
#       with the same style archetype as the retiring fighter.
#   D4. The new fighter enters with default attributes (all 50),
#       personality (all 50), and career (0-0-0, career_health=100).
#       Future Stage 3 tasks (training camps, scouting) will give them
#       growth potential — for now they're a generic prospect.
#   D5. The new fighter's DOB makes them 18-26 years old (young
#       prospect). Computed by subtracting age_years * 365 days + a
#       random offset within the year from the current_date. Approximate
#       (doesn't account for leap years) but close enough for sim
#       purposes — the age is recomputed from DOB when needed.
# ----------------------------------------------------------------

def generate_fighter(conn, style_dna_source_id=None, current_date=None, gender='male'):
    """Generate a new fighter from the name pool with a similar style DNA.

    Called by the retirement path (Task ID 14) when a fighter retires.
    The new fighter:
      - Has a unique name (first + last) drawn from the name pools,
        checked against existing fighters to avoid duplicates.
      - Has a nickname drawn from the nickname pool (50% chance of
        having one).
      - Has the same fight_style_archetype_id as the retiring fighter
        (style DNA). If style_dna_source_id is None, picks a random
        archetype.
      - Has a random DOB making them 18-26 years old (young prospect).
      - Has default attributes (all 50), personality (all 50), and
        career (0-0-0, career_health=100).
      - Enters as a FREE AGENT (current_promotion_id=NULL, is_active=1,
        is_retired=0).
      - Does NOT get a rankings row at generation time (rankings
        require a promotion_id; the row is created defensively by
        _update_rankings_after_resolution when the fighter is signed
        and fights their first fight — see D2 above).
      - Does NOT get a contract (they're a free agent — the player or
        AI signs them via Task 13's sign_free_agent).
      - Is assigned to a random weight class (for now — future
        matchmaking will refine this).
      - Is assigned to NO gym (current_gym_id=NULL is fine — future
        training camp features in Task 16 will assign gyms).
      - Triggers a "new prospect" news item so the player sees them
        arrive in the Free Agents tab.

    Args:
        conn: sqlite3 connection (caller commits).
        style_dna_source_id: the retiring fighter's fighter_id. The
            new fighter inherits their fight_style_archetype_id. If
            None, picks a random archetype.
        current_date: ISO date string 'YYYY-MM-DD' for the regen
            news item's published_at timestamp and for computing the
            new fighter's DOB. If None, uses today's wall-clock date
            via datetime.now().
        gender: 'male' or 'female'. Determines which first name pool
            to draw from. Default 'male'.

    Returns:
        New fighter_id (int) on success, None on failure (e.g., name
        pool exhausted — all name combinations already used).
    """
    # 1. Pick a first name from the appropriate pool.
    name_type = 'first_male' if gender == 'male' else 'first_female'
    firsts = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type = ?",
        (name_type,),
    ).fetchall()
    if not firsts:
        print(f"Warning: name pool empty for {name_type} — cannot generate fighter.")
        return None

    # 2. Pick a last name.
    lasts = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type = 'last'"
    ).fetchall()
    if not lasts:
        print("Warning: name pool empty for last — cannot generate fighter.")
        return None

    # 3. Find a unique (first, last) combination not already in the
    #    fighters table. Shuffle both lists so different calls produce
    #    different names (random.shuffle is in-place, so we convert
    #    tuples to lists first). Walks the cartesian product looking
    #    for the first unused combination. With 25 firsts × 26 lasts
    #    = 650 possible combinations vs. ~5-20 active fighters, the
    #    pool is effectively infinite for any realistic playthrough —
    #    but the defensive None return path exists for the test that
    #    artificially shrinks the pool.
    first_list = [f[0] for f in firsts]
    last_list = [l[0] for l in lasts]
    random.shuffle(first_list)
    random.shuffle(last_list)
    chosen_first = None
    chosen_last = None
    for f in first_list:
        for l in last_list:
            existing = conn.execute(
                "SELECT 1 FROM fighters WHERE first_name = ? AND last_name = ?",
                (f, l),
            ).fetchone()
            if existing is None:
                chosen_first, chosen_last = f, l
                break
        if chosen_first is not None:
            break
    if chosen_first is None:
        print("Warning: all name combinations exhausted — cannot generate unique fighter.")
        return None

    # 4. Nickname — deferred to step 10.5 (after attrs + pers are
    #    generated, so the nickname can be based on the fighter's
    #    actual attributes/personality/style via fighter_gen.generate_
    #    nickname). v2.6.3: replaced the old fixed-pool approach.
    nickname = None  # will be set in step 10.5

    # 5. Determine style archetype (style DNA).
    #
    #    v2.6.2 (user directive): DNA inheritance is OCCASIONAL, not
    #    always. Previously the regen always copied the retiring fighter's
    #    archetype, which makes the DB repeat itself over time — the same
    #    archetypes cycle through the same weight classes forever. Now:
    #      - 30% chance: inherit the retiring fighter's archetype (style
    #        DNA continuity — "the new generation Wrestler from Dagestan")
    #      - 70% chance: pick a random archetype (weighted by the retiring
    #        fighter's nation, so a Brazilian replacement is still likely
    #        to be a Grappler even if not the same archetype as the retiree)
    #
    #    This produces realistic variety: some successors carry the torch,
    #    most are new fighters with their own style.
    style_archetype_id = None
    if style_dna_source_id is not None and random.random() < 0.30:
        # 30% chance: inherit style DNA
        row = conn.execute(
            "SELECT fight_style_archetype_id FROM fighters WHERE fighter_id = ?",
            (style_dna_source_id,),
        ).fetchone()
        if row:
            style_archetype_id = row[0]
    if style_archetype_id is None:
        # 70% chance (or no source fighter): pick a random archetype.
        # v2.6.2: if we know the retiring fighter's nation, weight the
        # archetype selection by national tendency (a Brazilian successor
        # is more likely to be a Grappler, a Dagestani more likely to be
        # a Wrestler). This keeps national identity even when the
        # archetype isn't directly inherited.
        nation_name = None
        if style_dna_source_id is not None:
            loc_row = conn.execute(
                "SELECT n.name FROM fighters f JOIN nations n ON n.nation_id=f.birth_nation_id "
                "WHERE f.fighter_id = ?",
                (style_dna_source_id,),
            ).fetchone()
            if loc_row:
                nation_name = loc_row[0]
        # Use the nation-archetype weighting from Phase 3 (imported lazily
        # to avoid circular imports at module load). If nation_name is
        # None or the nation has no overrides, fall back to uniform random.
        if nation_name:
            try:
                # Lazy import — the seed scripts are in scripts/, not src/,
                # so we can't import them directly. Instead, replicate the
                # NATION_ARCHETYPE_OVERRIDES logic inline (small dict).
                # This is a known duplication — if the overrides change in
                # Phase 3, they must be updated here too. Documented in
                # the worklog as decision D7.
                from collections import defaultdict
                _BASE_WEIGHTS = {
                    "Balanced": 25, "Striker": 18, "Grappler": 15,
                    "Wrestler": 15, "Brawler": 10, "Counter-Striker": 10,
                    "Submission Specialist": 7,
                }
                _NATION_OVERRIDES = {
                    "Brazil":       {"Grappler": 20, "Submission Specialist": 15, "Striker": 5},
                    "Dagestan":     {"Wrestler": 30, "Grappler": 10},
                    "Russia":       {"Wrestler": 15, "Grappler": 10, "Submission Specialist": 5},
                    "Japan":        {"Striker": 10, "Wrestler": 5, "Submission Specialist": 8},
                    "Netherlands":  {"Striker": 20, "Counter-Striker": 10},
                    "Cuba":         {"Striker": 15, "Wrestler": 10},
                    "Mexico":       {"Striker": 10, "Brawler": 15},
                    "United States":{"Wrestler": 10, "Striker": 5, "Balanced": 5},
                    "United Kingdom":{"Striker": 12, "Brawler": 8},
                    "Ireland":      {"Striker": 15, "Brawler": 10},
                    "Nigeria":      {"Striker": 12, "Brawler": 8},
                    "South Korea":  {"Striker": 8, "Wrestler": 8, "Submission Specialist": 5},
                    "Australia":    {"Striker": 8, "Grappler": 5, "Balanced": 5},
                    "Canada":       {"Wrestler": 8, "Balanced": 5},
                    "France":       {"Striker": 10, "Submission Specialist": 8},
                    "Germany":      {"Wrestler": 10, "Striker": 5},
                    "Poland":       {"Striker": 8, "Brawler": 8},
                    "Sweden":       {"Wrestler": 10, "Striker": 5},
                    "China":        {"Striker": 8, "Wrestler": 8, "Submission Specialist": 5},
                    "Argentina":    {"Grappler": 10, "Striker": 8},
                }
                weights = dict(_BASE_WEIGHTS)
                if nation_name in _NATION_OVERRIDES:
                    for arch, bonus in _NATION_OVERRIDES[nation_name].items():
                        weights[arch] = weights.get(arch, 0) + bonus
                # Fetch all archetype names + IDs
                archetypes = conn.execute(
                    "SELECT style_archetype_id, name FROM style_archetypes"
                ).fetchall()
                # Build weighted list
                names = [a[1] for a in archetypes]
                w = [weights.get(n, 1) for n in names]
                chosen_name = random.choices(names, weights=w, k=1)[0]
                style_archetype_id = next(
                    (a[0] for a in archetypes if a[1] == chosen_name), None
                )
            except Exception:
                # Fallback: uniform random
                row = conn.execute(
                    "SELECT style_archetype_id FROM style_archetypes ORDER BY RANDOM() LIMIT 1"
                ).fetchone()
                style_archetype_id = row[0] if row else None
        else:
            row = conn.execute(
                "SELECT style_archetype_id FROM style_archetypes ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            style_archetype_id = row[0] if row else None

    # 6. Determine personality archetype (random).
    row = conn.execute(
        "SELECT personality_archetype_id FROM personality_archetypes "
        "ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    pers_archetype_id = row[0] if row else None

    # 7. Compute DOB (18-26 years old). Approximate: subtract
    #    age_years * 365 days + a random offset within the year. Does
    #    not account for leap years but the resulting DOB is "close
    #    enough" — age is recomputed from DOB whenever needed.
    if current_date:
        try:
            current_dt = datetime.strptime(current_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            current_dt = datetime.now()
    else:
        current_dt = datetime.now()
    age_years = random.randint(18, 26)
    dob_dt = current_dt - timedelta(days=age_years * 365 + random.randint(0, 364))
    dob = dob_dt.strftime("%Y-%m-%d")

    # 8. Pick a random weight class (defensive: if no weight classes
    #    exist, wc_id stays None — the column is nullable).
    row = conn.execute(
        "SELECT weight_class_id FROM weight_classes ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    wc_id = row[0] if row else None

    # 9. Insert the fighter as a free agent. current_promotion_id=NULL
    #    and current_gym_id=NULL — they enter the world unsigned and
    #    unaffiliated. is_active=1 (they're available to be booked
    #    once signed), is_retired=0 (they're a fresh prospect).
    #    v2.0.0 (Task 14.5): also insert the 4 physical columns
    #    (height_cm, reach_cm, stance, handedness) from
    #    fighter_gen.generate_physical_block() so regen prospects
    #    arrive with a body, not just a name.
    #
    #    v2.6.1 (forensic audit fix): also insert the 7 meta-columns
    #    (injury_proneness, weight_cut_difficulty, consistency,
    #    clutch_factor, marketability, fan_friendliness, promo_boost)
    #    with randomized values (was using schema defaults of 50).
    #    Also insert birth_city_id + birth_nation_id inherited from
    #    the retiring fighter (region-aware regen). Also assign a
    #    gym in the retiring fighter's nation (so the new prospect
    #    can participate in training camps immediately).
    #
    #    Lazy-import fighter_gen here (not at module top) so app.py
    #    can still be imported in headless contexts that don't have
    #    a src/ on sys.path (e.g., the existing tests that import
    #    app directly).
    import fighter_gen  # noqa: E402 — local import, see comment above
    # v2.6.3: pass weight class max_weight_kg + gender for height scaling
    wc_max_kg = None
    if wc_id is not None:
        wc_row = conn.execute(
            "SELECT max_weight_kg FROM weight_classes WHERE weight_class_id=?",
            (wc_id,),
        ).fetchone()
        if wc_row:
            wc_max_kg = wc_row[0]
    physical = fighter_gen.generate_physical_block(wc_max_kg, gender)

    # v2.6.1: inherit birth location from retiring fighter (region-
    # aware regen — a retiring Brazilian fighter spawns a Brazilian
    # replacement, not a random nationality).
    birth_city_id = None
    birth_nation_id = None
    if style_dna_source_id is not None:
        loc_row = conn.execute(
            "SELECT birth_city_id, birth_nation_id FROM fighters "
            "WHERE fighter_id = ?",
            (style_dna_source_id,),
        ).fetchone()
        if loc_row:
            birth_city_id, birth_nation_id = loc_row

    # v2.6.2 (user directive): NOT all regen fighters get a gym. The
    # user wants some fighters to enter with current_gym_id=NULL —
    # young prospects who haven't settled at a gym yet, or free agents
    # who train independently. Future gym-joining logic will use
    # personality + attributes + age to decide whether a fighter joins
    # a gym and which one. For now:
    #   - 50% chance: assign a gym in the retiring fighter's nation
    #     (if one exists)
    #   - 50% chance: leave gym NULL (the fighter trains independently
    #     until signed + the future gym-joining logic runs)
    gym_id = None
    if random.random() < 0.50 and birth_nation_id is not None:
        gym_row = conn.execute(
            "SELECT gym_id FROM gyms WHERE nation_id = ? "
            "ORDER BY RANDOM() LIMIT 1",
            (birth_nation_id,),
        ).fetchone()
        if gym_row:
            gym_id = gym_row[0]

    # v2.6.1: randomized meta-columns (was all 50).
    injury_proneness = random.randint(20, 80)
    weight_cut_diff = random.randint(20, 80)
    consistency = random.randint(40, 80)
    clutch_factor = random.randint(40, 80)
    marketability = random.randint(30, 90)
    fan_friendliness = random.randint(30, 90)
    promo_boost = random.randint(20, 80)

    fid = conn.execute(
        "INSERT INTO fighters (first_name, last_name, nickname, gender, "
        "date_of_birth, birth_city_id, birth_nation_id, "
        "weight_class_id, current_gym_id, current_promotion_id, "
        "fight_style_archetype_id, personality_archetype_id, "
        "is_active, is_retired, height_cm, reach_cm, stance, handedness, "
        "injury_proneness, weight_cut_difficulty, consistency, "
        "clutch_factor, marketability, fan_friendliness, promo_boost) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1, 0, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?)",
        (chosen_first, chosen_last, nickname, gender, dob,
         birth_city_id, birth_nation_id, wc_id, gym_id,
         style_archetype_id, pers_archetype_id,
         physical["height_cm"], physical["reach_cm"],
         physical["stance"], physical["handedness"],
         injury_proneness, weight_cut_diff, consistency,
         clutch_factor, marketability, fan_friendliness, promo_boost),
    ).lastrowid

    # 10. Insert attributes, personality, career rows. v2.0.0
    #     (Task 14.5): the attribute and personality blocks are now
    #     generated via fighter_gen with archetype bias — regen
    #     prospects feel like real fighters of their archetype, not
    #     generic 50-everything stubs (see decision D4-update in the
    #     worklog). The career row still uses all defaults
    #     (0-0-0, career_health=100) — Stage 3 training camps will
    #     give them growth potential.
    #
    #     v2.6.1 (forensic audit fix): widen personality variation
    #     the same way Phase 3 does — fighter_gen produces 32-68
    #     range; we scale away from 50 by 1.3-2.0x + ±5 noise,
    #     clamped to [10, 95]. Without this, regen fighters have
    #     bland personalities compared to seeded fighters.
    #
    #     The 25 attribute columns are INSERTed explicitly (not via
    #     `INSERT INTO fighter_attributes (fighter_id) VALUES (?)`
    #     which would give all-50 defaults). Same for the 20
    #     personality columns. The SQL is built dynamically from the
    #     fighter_gen.ATTRIBUTE_NAMES / PERSONALITY_NAMES lists so a
    #     future column addition doesn't require touching this code.
    attrs = fighter_gen.generate_attribute_block(style_archetype_id, conn)
    pers = fighter_gen.generate_personality_block(pers_archetype_id, conn)

    # v2.6.1: widen personality variation (matches Phase 3's approach).
    for k in pers:
        base = pers[k]
        dist_from_50 = base - 50
        scale = random.uniform(1.3, 2.0)
        widened = int(50 + dist_from_50 * scale + random.randint(-5, 5))
        pers[k] = max(10, min(95, widened))

    # 10.5. v2.6.3: generate nickname dynamically based on the fighter's
    #      actual attributes, personality, style, and nation. Replaces
    #      the old fixed-pool-of-38 approach.
    style_arch_name_for_nick = None
    if style_archetype_id is not None:
        sa_row = conn.execute(
            "SELECT name FROM style_archetypes WHERE style_archetype_id=?",
            (style_archetype_id,),
        ).fetchone()
        if sa_row:
            style_arch_name_for_nick = sa_row[0]
    nation_name_for_nick = None
    if birth_nation_id is not None:
        n_row = conn.execute(
            "SELECT name FROM nations WHERE nation_id=?",
            (birth_nation_id,),
        ).fetchone()
        if n_row:
            nation_name_for_nick = n_row[0]
    nickname = fighter_gen.generate_nickname(
        attrs=attrs, pers=pers,
        style_archetype_name=style_arch_name_for_nick,
        nation_name=nation_name_for_nick, rng=random,
    )

    # v2.6.3: UPDATE the fighter row with the generated nickname (was
    # inserted as NULL in step 9 because attrs/pers weren't available yet).
    if nickname is not None:
        conn.execute(
            "UPDATE fighters SET nickname=? WHERE fighter_id=?",
            (nickname, fid),
        )

    attr_cols = fighter_gen.ATTRIBUTE_NAMES
    attr_placeholders = ", ".join(["?"] * len(attr_cols))
    attr_col_list = ", ".join(attr_cols)
    conn.execute(
        f"INSERT INTO fighter_attributes (fighter_id, {attr_col_list}) "
        f"VALUES (?, {attr_placeholders})",
        (fid,) + tuple(attrs[c] for c in attr_cols),
    )

    pers_cols = fighter_gen.PERSONALITY_NAMES
    pers_placeholders = ", ".join(["?"] * len(pers_cols))
    pers_col_list = ", ".join(pers_cols)
    conn.execute(
        f"INSERT INTO fighter_personality (fighter_id, {pers_col_list}) "
        f"VALUES (?, {pers_placeholders})",
        (fid,) + tuple(pers[c] for c in pers_cols),
    )

    # v2.0.1 (Task pre-B1-fixes): set `potential` for the new fighter
    # via fighter_gen.generate_potential(). The distribution is 10%
    # elite (70-90), 30% solid (50-69), 60% limited (25-49). The
    # fighter_career row INSERT now specifies `potential` explicitly
    # (was `INSERT INTO fighter_career (fighter_id) VALUES (?)` which
    # used the DEFAULT 50). All other fighter_career columns (record,
    # streaks, career_health, title_reigns) use their schema DEFAULTs
    # (0-0-0, 100, 0) — sensible for a fresh prospect.
    #
    # Why potential matters: without a growth ceiling, every fighter
    # has unlimited growth potential and the Talent Hunter fantasy
    # collapses (CAGE_EMPIRE_SOUL.md Fantasy 1). With potential,
    # training camps (Task 16, future) will push attributes toward
    # this ceiling with diminishing returns as they approach it. The
    # rare-elite distribution makes "that kid from Mexico" prospects
    # genuinely rare — ~1 in 10 regen fighters has elite potential.
    potential = fighter_gen.generate_potential()
    conn.execute(
        "INSERT INTO fighter_career (fighter_id, potential) VALUES (?, ?)",
        (fid, potential),
    )

    # 11. NO rankings row at generation time. See D2 above — the
    #     rankings table requires a promotion_id (NOT NULL), and the
    #     new fighter is a free agent. _get_or_create_ranking_row in
    #     app.py creates the rankings row on the fly when the fighter
    #     is signed and fights their first bout.

    # 12. Write a news item about the new prospect. Direct INSERT
    #     (same pattern as _check_retirements, _vacate_title_on_retirement,
    #     sign_free_agent — avoids pulling in app.write_news from
    #     this same module). topic='prospect' so the future news
    #     engine (Task 23) can filter prospect-arrival news.
    src = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if src is None:
        src_id = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        ).lastrowid
    else:
        src_id = src[0]

    nick_str = f' "{nickname}"' if nickname else ''
    headline = f"New prospect {chosen_first} {chosen_last}{nick_str} emerges on the scene"
    body = (f"A new talent, {chosen_first} {chosen_last}{nick_str}, has arrived "
            f"as a free agent looking for a promotion to sign with.")
    # published_at: prefer the explicit current_date (the sim date the
    # regen happened on). If None (caller didn't pass one), fall back to
    # today's wall-clock date. The news_items.published_at column is
    # NOT NULL with a DEFAULT of CURRENT_TIMESTAMP, but we explicitly
    # pass a value here so the caller controls the timestamp. Direct
    # callers (e.g., the test in case K) that omit current_date get
    # today's date — matching the pattern in app.write_news which also
    # omits published_at (letting the DEFAULT apply, which is wall-clock
    # time). For consistency with the rest of the regen path which
    # passes the sim date, we use today's date string instead of relying
    # on the DEFAULT (so the published_at is a clean YYYY-MM-DD, not a
    # full CURRENT_TIMESTAMP).
    if current_date:
        published_at = current_date
    else:
        published_at = current_dt.strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO news_items (news_source_id, headline, body, sentiment, "
        "topic, fighter_id, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (src_id, headline, body, "neutral", "prospect", fid, published_at),
    )

    # 13. v2.6.2 (user directive): generate a bio for EVERY regen
    #     fighter, not just elite-potential ones. This matches the
    #     Phase 5 change where all 4000 active fighters get bios.
    #     The bio tone is 'unproven_prospect' for all regen fighters
    #     (they're young, few fights, unknown ceiling) — this does NOT
    #     reveal potential. A limited-potential regen and an elite-
    #     potential regen get identical bios.
    gym_name = "an independent camp"
    if gym_id is not None:
        g_row = conn.execute(
            "SELECT name FROM gyms WHERE gym_id=?", (gym_id,)
        ).fetchone()
        if g_row:
            gym_name = g_row[0]
    sa_name = "well-rounded fighter"
    if style_archetype_id is not None:
        sa_row = conn.execute(
            "SELECT name FROM style_archetypes WHERE style_archetype_id=?",
            (style_archetype_id,),
        ).fetchone()
        if sa_row:
            sa_name = sa_row[0]
    nick_str = f' "{nickname}"' if nickname else ''
    total_fights = 0  # regen fighters start at 0-0-0
    import random as _bio_rng
    bio_variants = [
        f"{chosen_first} {chosen_last}{nick_str} is {age_years} years old with a {total_fights}-{total_fights} record and everything still to prove. The {sa_name.lower()} out of {gym_name} has shown flashes in 'his' early training, but the sample size is small and the competition hasn't been elite. Whether 'he' develops into a contender or settles into the mid-card is an open question — one that only time and fights will answer.",
        f"Early career. That's the entire resume for {chosen_first} {chosen_last}{nick_str}, a {age_years}-year-old {sa_name.lower()} training out of {gym_name}. The tools are there — whether they translate against real opposition is what the next few years will determine. Right now, 'he' is a question mark with potential.",
        f"There's a version of the future where {chosen_first} {chosen_last}{nick_str} is a champion. There's also a version where 'he' flames out by 25. At {age_years} with no professional fights, the {sa_name.lower()} from {gym_name} is at the starting line every young fighter hits — the jump from prospect to contender is the hardest one to make.",
        f"{chosen_first} {chosen_last}{nick_str} has the look of a fighter who could go either way. The {age_years}-year-old {sa_name.lower()} out of {gym_name} is just starting 'his' career — not enough data to know if 'he' is a future title challenger or a career gatekeeper. The next few fights will tell us which.",
    ]
    bio_text = _bio_rng.choice(bio_variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")
    conn.execute(
        "INSERT OR REPLACE INTO fighter_bios (fighter_id, bio_text, bio_tone) "
        "VALUES (?, ?, ?)",
        (fid, bio_text, "unproven_prospect"),
    )

    # 14. Return the new fighter_id. The caller (tick_processor's
    #     _check_retirements) writes the regen_lineage row linking the
    #     retiring fighter to this replacement.
    #
    # Phase A5 — publish FIGHTER_GENERATED on the event bus. The news
    # engine subscribes to write a richer "new prospect emerges" news
    # item (the inline 'prospect' topic item above is the placeholder;
    # the event-driven item has voice descriptors). Lazy import to
    # avoid any circular dependency issues.
    try:
        from event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(conn, {
            'type': Events.FIGHTER_GENERATED,
            'fighter_id': fid,
            'current_date': published_at,
            'event_date': published_at,
        })
    except ImportError:
        pass

    return fid



# ----------------------------------------------------------------
# Title vacation on retirement (Task ID 12).
#
# When a fighter retires (handled by _check_retirements in
# tick_processor.py), any title they currently hold is vacated.
# This helper does the vacation + writes a news item about it. It
# lives here in app.py (next to _resolve_title_after_fight) so all
# title-mutation logic is in one place — tick_processor.py imports
# it via `from app import _vacate_title_on_retirement`. There is no
# circular-import risk because app.py does NOT import tick_processor.
#
# Vacation rules:
#   - current_champion_fighter_id  -> NULL
#   - champion_since_date          -> NULL
#   - is_vacant                    -> 1
#   - title_reigns_count and title_defenses_count are PRESERVED
#     (they're historical counters — a vacated belt still represents
#     a completed reign, and the count of past reigns is meaningful
#     for legacy/Hall-of-Fame work in later tasks).
#   - A news item is written: "<fighter> vacates the <promo> <wc>
#     title" with topic='retirement', promotion_id set, fighter_id
#     set, published_at=current_date.
#
# Returns the list of vacated title_ids (empty list if the fighter
# held no titles). Caller commits.
# ----------------------------------------------------------------




def _vacate_title_on_retirement(conn, fighter_id, current_date):
    """Vacate any title held by a retiring fighter.

    Called by _check_retirements() in tick_processor.py when a fighter
    retires. If the retiring fighter is a current champion, the title
    is vacated (current_champion_fighter_id = NULL, is_vacant = 1,
    champion_since_date = NULL). title_reigns_count and
    title_defenses_count are NOT reset (they're historical counters
    that should survive across reigns for legacy/Hall-of-Fame work).

    Also writes a news item about each title vacation (INSERT directly
    into news_items rather than going through app.write_news — see
    decision D2 in the worklog). The news item carries the fighter_id
    and promotion_id so future UIs can filter "retirement" news per
    promotion or per fighter.

    Args:
        conn: sqlite3 connection (caller commits).
        fighter_id: the retiring fighter's fighter_id.
        current_date: ISO date string 'YYYY-MM-DD' for the news item
            published_at column.

    Returns:
        List of title_ids that were vacated (empty list if the fighter
        held no titles).
    """
    vacated = []
    # Find every title the retiring fighter currently holds. In
    # practice a fighter holds at most 1 title (one per weight class
    # per promotion, and a fighter is in one weight class), but the
    # code is defensive — if a future task adds multi-division
    # champions, this loop handles it correctly.
    rows = conn.execute(
        "SELECT title_id, promotion_id, weight_class_id "
        "FROM titles WHERE current_champion_fighter_id = ?",
        (fighter_id,),
    ).fetchall()
    if not rows:
        return vacated

    # Look up the fighter's name once (used in every news item).
    fighter_name_row = conn.execute(
        "SELECT first_name || ' ' || last_name FROM fighters WHERE fighter_id = ?",
        (fighter_id,),
    ).fetchone()
    fighter_name = fighter_name_row[0] if fighter_name_row else f"Fighter {fighter_id}"

    # Get or create the "System Feed" news source (same pattern as
    # app.write_news). In the seeded DB this source already exists.
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

    for title_id, promo_id, wc_id in rows:
        # Vacate the title. Preserve reigns + defenses counts (they
        # are historical — a future champion will start a NEW reign
        # with title_reigns_count incremented, but the historical
        # count of past reigns stays).
        conn.execute(
            "UPDATE titles SET current_champion_fighter_id = NULL, "
            "champion_since_date = NULL, is_vacant = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE title_id = ?",
            (title_id,),
        )
        vacated.append(title_id)

        # Look up promotion + weight class names for the news headline.
        promo_row = conn.execute(
            "SELECT name FROM promotions WHERE promotion_id = ?",
            (promo_id,),
        ).fetchone()
        promo_name = promo_row[0] if promo_row else f"Promotion {promo_id}"
        wc_row = conn.execute(
            "SELECT name FROM weight_classes WHERE weight_class_id = ?",
            (wc_id,),
        ).fetchone()
        wc_name = wc_row[0] if wc_row else f"Weight Class {wc_id}"

        # Write the vacation news item. topic='retirement' so future
        # UI filters can group retirement-related news together.
        # published_at is set to current_date (the sim date the
        # retirement happened on), NOT CURRENT_TIMESTAMP (which is
        # the wall-clock time the row was inserted).
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, promotion_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                src_id,
                f"{fighter_name} vacates the {promo_name} {wc_name} title",
                f"{fighter_name} has retired, vacating the {promo_name} "
                f"{wc_name} championship. A new champion will be crowned "
                f"at the next title fight.",
                "neutral",
                "retirement",
                fighter_id,
                promo_id,
                current_date,
            ),
        )

    return vacated




# ----------------------------------------------------------------
# Thin wrapper around tick_processor._check_retirements.
#
# Per docs/TASK_6_0_PLAN.md §1.1 + §2.1, services.retirement_svc
# exposes a thin wrapper around tick_processor._check_retirements so
# the future GUI (Task 6.11 Hall of Fame + Task 6.3 Dashboard) can
# call "retirement checks" via the service layer without depending
# directly on tick_processor. The orchestration (clock advance →
# retirement → contract expiry → injury recovery → commit) stays in
# tick_processor.run_tick for Task 6.0 (per Plan agent Fix #2); a
# future task (6.0.5, optional) may move that orchestration into
# services.clock.advance_day.
#
# The lazy import (inside the function body, not at module top)
# avoids a circular import: tick_processor imports from app.py, app
# re-exports from retirement_svc, so retirement_svc must NOT import
# tick_processor at module top.
# ----------------------------------------------------------------


def check_retirements(conn):
    """Thin wrapper that delegates to tick_processor._check_retirements.

    Note: _check_retirements takes (conn, current_date) in
    tick_processor, NOT just (conn). The wrapper here preserves the
    brief's literal signature (single `conn` arg) by reading the
    current sim date from the simulation_clock row before delegating.
    This matches the pattern used by services.clock.advance_day
    (which also reads the clock before delegating to run_tick).
    """
    from tick_processor import _check_retirements
    row = conn.execute(
        "SELECT simulation_clock.current_date "
        "FROM simulation_clock WHERE clock_id = 1"
    ).fetchone()
    current_date = row[0] if row else None
    if current_date is None:
        return []  # defensive — no clock row, no retirements
    return _check_retirements(conn, current_date)
