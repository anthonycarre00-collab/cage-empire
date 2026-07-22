#!/usr/bin/env python3
"""World seed Phase 5: Narrative layer — bios, retired legends, news.

Run AFTER Phase 4. Idempotent.

Creates:
  - Fighter bios for the top ~200 "featured" fighters (champions,
    top contenders, top prospects, notable veterans). Each bio is a
    2-4 sentence prose bio with a bio_tone hint for the voice layer.
  - Retired legends in the hall_of_fame table (~50-80). These are
    fictional retired fighters with career summaries + highlights.
    They're stored as retired fighters (is_retired=1) with a
    hall_of_fame row.
  - Memory links for champion successors (champion-only per the
    pre-B1 fix decision).
  - ~500 historical news items covering past milestones (title wins,
    upsets, retirements, debuts).

Per docs/WORLD_SEED_ANALYSIS.md Phase 5. Per CONVENTIONS §16.8.

Usage:
    python scripts/seed_world_phase5.py
"""
import sqlite3
import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"

random.seed(20260725)

SIM_DATE = datetime(2026, 7, 22)


# ----------------------------------------------------------------
# Bio templates by tone. Each template is a function that takes
# fighter data and returns a prose bio string.
# ----------------------------------------------------------------
def _bio_champion_reign(f):
    """Bio for a current champion."""
    name = f"{f['first_name']} {f['last_name']}"
    if f['nickname']:
        name += f" '{f['nickname']}'"
    wc = f['weight_class_name']
    promo = f['promotion_name']
    wins = f['record_wins']
    losses = f['record_losses']
    defenses = f['title_defenses']
    reign_len = f['reign_days']
    # 3 variants to avoid repetition
    variants = [
        f"{name} sits atop the {promo} {wc} division with the confidence of a champion who has earned every inch of the belt. {reign_len} days into the reign, {f['first_name']} has defended {defenses} time{'s' if defenses != 1 else ''} and shows no signs of loosening 'his' grip. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} trains at {f['gym_name']}, where the game plan is simple: keep winning.",
        f"The {promo} {wc} title has found a home around {f['first_name']} {f['last_name']}'s waist. Since claiming the belt {reign_len} days ago, the {f['age']}-year-old has turned back {defenses} challenger{'s' if defenses != 1 else ''} with the kind of disciplined {_archetype_noun(f['style_archetype_name'])} approach drilled into 'him' at {f['gym_name']}. At {wins}-{losses}, the resume speaks for itself.",
        f"{reign_len} days as {promo} {wc} champion. {defenses} successful defenses. A {wins}-{losses} record forged in the sport's toughest rooms. {f['first_name']} {f['last_name']} didn't stumble into this — the {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} put in the work at {f['gym_name']} and now reaps the reward. The question isn't whether 'he' belongs at the top, but how long 'he' stays there.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


def _bio_hype_prospect(f):
    """Bio for a top prospect."""
    name = f"{f['first_name']} {f['last_name']}"
    wc = f['weight_class_name']
    promo = f['promotion_name']
    wins = f['record_wins']
    losses = f['record_losses']
    variants = [
        f"The buzz around {name} started before 'he' ever stepped into a {promo} cage. Now {wins}-{losses} later, the {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} is making the scouts look smart. Training at {f['gym_name']}, {f['first_name']} brings a maturity to 'his' game that belies the birth certificate. The {wc} division is on notice.",
        f"{f['age']} years old, {wins}-{losses}, and already drawing comparisons to fighters who took a decade to reach this level. {f['first_name']} {f['last_name']} is the kind of prospect that makes {promo} matchmakers salivate — a {_archetype_noun(f['style_archetype_name'])} with the tools to dominate at {wc}. The work at {f['gym_name']} is paying off faster than anyone expected.",
        f"Some prospects are hype. Some are the real thing. {name} is forcing {promo} to figure out which one 'he' is, fast. At {f['age']}, the {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has already compiled a {wins}-{losses} record that turned heads in the {wc} division. The ceiling is high — the question is how quickly 'he' reaches it.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


def _bio_grizzled_veteran(f):
    """Bio for a long-tenured veteran."""
    name = f"{f['first_name']} {f['last_name']}"
    wins = f['record_wins']
    losses = f['record_losses']
    total = wins + losses
    variants = [
        f"{total} professional fights. That number alone tells you what {name} is made of. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has been in there with champions, contenders, and hype trains — and sent most of them home disappointed. The {wins}-{losses} record is a war chest. These days, every fight is borrowed time.",
        f"There's a version of MMA history you can't write without {f['first_name']} {f['last_name']}. Over {total} fights, the {_archetype_noun(f['style_archetype_name'])} from {f['gym_name']} has been the test opponents either pass or fail. At {f['age']}, the {wins}-{losses} veteran doesn't need to prove anything to anyone — but 'he' keeps showing up anyway.",
        f"The young guys think they want smoke with {name}. They usually change their minds. {total} fights deep, {wins}-{losses}, and still going — the {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} has made {f['gym_name']} 'his' home base for a career that spans eras. Father Time is undefeated, but {f['first_name']} is making 'him' work for it.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


def _bio_fallen_contender(f):
    """Bio for a former contender on a losing streak."""
    name = f"{f['first_name']} {f['last_name']}"
    wins = f['record_wins']
    losses = f['record_losses']
    variants = [
        f"There was a time when {name} felt inevitable — a fighter marching toward the title with each appearance. That was before the slide. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} still trains at {f['gym_name']}, still puts in the rounds, but the {wins}-{losses} record hides a recent skid that has the division writing 'him' off. One more loss could be the end. One win could be the start of something.",
        f"The {_archetype_noun(f['style_archetype_name'])} from {f['gym_name']} who once had the division worried is now the division's afterthought. {f['first_name']} {f['last_name']} knows the story — {wins}-{losses} doesn't lie, but it doesn't tell the whole truth either. At {f['age']}, 'he' needs a performance that reminds everyone what 'he' was before the losses piled up.",
        f"Scan the {_archetype_noun(f['style_archetype_name'])}'s record and you'll find the turning point — the fight where {name} stopped being a contender and started being a question mark. The {f['age']}-year-old still has the skill that got 'him' to {wins}-{losses}. What 'he' doesn't have anymore is margin for error. Every fight now is an audition for 'his' own future.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


def _bio_journeyman(f):
    """Bio for a career journeyman."""
    name = f"{f['first_name']} {f['last_name']}"
    wins = f['record_wins']
    losses = f['record_losses']
    variants = [
        f"Every promotion needs a fighter like {name}. Someone tough enough to test the prospects, experienced enough to expose the not-ready-yets, and professional enough to show up on short notice when the card falls apart. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has built a {wins}-{losses} career on being exactly that fighter.",
        f"{wins}-{losses}. No title belt. No Hall of Fame campaign. But ask anyone in the {_archetype_noun(f['style_archetype_name'])}'s weight class about {name} and they'll nod respectfully. The {f['age']}-year-old from {f['gym_name']} has been the litmus test for a generation of fighters — beat 'him' and you're ready. Lose to 'him' and you're not.",
        f"The unglamorous middle of the roster is where {f['first_name']} {f['last_name']} has made a living. {wins}-{losses} over a career that never quite reached the title picture but never fell out of it either. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} trains at {f['gym_name']}, shows up on weight, and fights whoever the promotion puts in front of 'him'. That's worth something.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


def _bio_cult_hero(f):
    """Bio for a fan-favorite cult hero."""
    name = f"{f['first_name']} {f['last_name']}"
    if f['nickname']:
        name += f" '{f['nickname']}'"
    wins = f['record_wins']
    losses = f['record_losses']
    variants = [
        f"The crowd erupts before the announcer even finishes the name. {name} isn't the champion and probably won't ever be — but try telling that to the fans who tune in specifically to watch 'him' fight. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has turned {wins}-{losses} into a cult following by doing one thing: coming to fight, every single time.",
        f"Some fighters win titles. Some fighters win fans. {f['first_name']} {f['last_name']} does the second one better than almost anyone in the sport. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} from {f['gym_name']} has a {wins}-{losses} record that won't make the Hall of Fame — but ask the arena faithful who they came to see and 'his' name comes up first.",
        f"You won't find {name} atop any rankings. You will find 'him' in the highlight reels, in the post-fight bonus records, and in the memories of fans who were in the building when 'he' did something nobody expected. {wins}-{losses}, {f['age']} years old, {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} — and absolutely incapable of a boring fight.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


BIO_TEMPLATES = {
    "champion_reign":    _bio_champion_reign,
    "hype_prospect":     _bio_hype_prospect,
    "grizzled_veteran":  _bio_grizzled_veteran,
    "fallen_contender":  _bio_fallen_contender,
    "journeyman":        _bio_journeyman,
    "cult_hero":         _bio_cult_hero,
}


# Map style_archetype_name → natural noun phrase for use in bios.
# "Balanced" doesn't work as a noun ("the 32-year-old balanced" reads
# awkwardly); "well-rounded fighter" does. The other archetypes work
# as nouns ("striker", "wrestler", "grappler") but get "specialist"
# appended for variety in some contexts.
_ARCHETYPE_NOUN = {
    "Balanced":              "well-rounded fighter",
    "Striker":               "striker",
    "Grappler":              "grappler",
    "Wrestler":              "wrestler",
    "Brawler":               "brawler",
    "Counter-Striker":       "counter-striker",
    "Submission Specialist": "submission specialist",
}


def _archetype_noun(name):
    """Convert a style_archetype_name to a natural noun phrase."""
    return _ARCHETYPE_NOUN.get(name, "fighter")


def _pick_bio_tone(f):
    """Pick the appropriate bio_tone for a fighter based on their stats."""
    # Current champion?
    if f.get('is_champion'):
        return "champion_reign"
    # Top prospect (young + high potential + few fights)?
    if f['age'] <= 23 and f['potential'] >= 70 and (f['record_wins'] + f['record_losses']) <= 6:
        return "hype_prospect"
    # Veteran with many fights?
    total_fights = f['record_wins'] + f['record_losses']
    if f['age'] >= 36 and total_fights >= 30:
        return "grizzled_veteran"
    # Fallen contender (losing streak)?
    if f.get('loss_streak', 0) >= 3 and f['record_wins'] >= 10:
        return "fallen_contender"
    # High fan_friendliness but not champion → cult hero
    if f.get('fan_friendliness', 50) >= 75:
        return "cult_hero"
    # Default: journeyman
    return "journeyman"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run Phase 1-4 first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Verify Phase 4 ran
    n_fh = conn.execute("SELECT COUNT(*) FROM fight_history").fetchone()[0]
    if n_fh < 10000:
        print(f"ERROR: Phase 4 not complete (only {n_fh} fight_history rows).")
        sys.exit(1)

    rng = random.Random(20260725)

    # ----------------------------------------------------------------
    # 1. Fighter bios for the top ~200 featured fighters.
    #    Featured = champions + top contenders + top prospects + notable veterans.
    # ----------------------------------------------------------------
    print("Generating fighter bios for top ~200 featured fighters...")

    # Get current champions
    champions = conn.execute(
        "SELECT t.current_champion_fighter_id, t.title_defenses_count, "
        "t.champion_since_date "
        "FROM titles t WHERE t.current_champion_fighter_id IS NOT NULL"
    ).fetchall()
    champion_ids = {r[0]: (r[1], r[2]) for r in champions}

    # Get top 100 by rating (contenders + prospects + veterans)
    top_fighters = conn.execute(
        "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
        "f.gender, f.date_of_birth, f.fight_style_archetype_id, "
        "f.current_gym_id, f.current_promotion_id, f.weight_class_id, "
        "f.marketability, f.fan_friendliness, "
        "fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.potential, fc.title_reigns, "
        "r.rating, sa.name AS style_archetype_name, "
        "wc.name AS weight_class_name, p.name AS promotion_name, "
        "g.name AS gym_name "
        "FROM fighters f "
        "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id=f.fighter_id "
        "LEFT JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
        "LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
        "LEFT JOIN promotions p ON p.promotion_id=f.current_promotion_id "
        "LEFT JOIN gyms g ON g.gym_id=f.current_gym_id "
        "ORDER BY r.rating DESC LIMIT 200"
    ).fetchall()

    n_bios = 0
    for row in top_fighters:
        (fid, first, last, nick, gender, dob, sa_id, gym_id, promo_id, wc_id,
         market, fan_friend, w, l, d, ws, ls, pot, reigns, rating,
         sa_name, wc_name, promo_name, gym_name) = row
        # Compute age
        try:
            dob_dt = datetime.strptime(dob, "%Y-%m-%d")
            age = (SIM_DATE - dob_dt).days // 365
        except (ValueError, TypeError):
            age = 30
        # Check if champion
        is_champ = fid in champion_ids
        defenses, champ_since = champion_ids.get(fid, (0, None))
        reign_days = 0
        if champ_since:
            try:
                reign_days = (SIM_DATE - datetime.strptime(champ_since, "%Y-%m-%d")).days
            except (ValueError, TypeError):
                reign_days = 0
        f_data = {
            'first_name': first, 'last_name': last, 'nickname': nick,
            'gender': gender, 'age': age, 'potential': pot,
            'record_wins': w, 'record_losses': l, 'record_draws': d,
            'win_streak': ws, 'loss_streak': ls,
            'is_champion': is_champ, 'title_defenses': defenses,
            'reign_days': reign_days,
            'style_archetype_name': sa_name or 'Balanced',
            'weight_class_name': wc_name or 'Lightweight',
            'promotion_name': promo_name or 'Alpha Combat Federation',
            'gym_name': gym_name or 'Ironhouse Gym',
            'fan_friendliness': fan_friend or 50,
            'marketability': market or 50,
        }
        bio_tone = _pick_bio_tone(f_data)
        bio_fn = BIO_TEMPLATES[bio_tone]
        bio_text = bio_fn(f_data)
        # Insert/replace bio (idempotent — re-running updates existing)
        conn.execute(
            "INSERT OR REPLACE INTO fighter_bios (fighter_id, bio_text, bio_tone) "
            "VALUES (?, ?, ?)",
            (fid, bio_text, bio_tone),
        )
        n_bios += 1
    conn.commit()
    print(f"  Fighter bios: {n_bios}")

    # ----------------------------------------------------------------
    # 2. Retired legends in the Hall of Fame (~60).
    #    These are fictional retired fighters. We create them as
    #    is_retired=1 fighters with a hall_of_fame row.
    # ----------------------------------------------------------------
    print("Generating retired legends (Hall of Fame)...")
    # Pull 60 names from the name pool — these are unique fighters
    # that don't exist in the active roster.
    used_names = {r[0] for r in conn.execute(
        "SELECT first_name || '|' || last_name FROM fighters"
    ).fetchall()}
    legend_count = 0
    LEGEND_COUNT = 60
    nations = [r[0] for r in conn.execute(
        "SELECT name FROM nations"
    ).fetchall()]
    # Get a few name pool entries per nation
    for _ in range(LEGEND_COUNT * 3):  # try up to 3x to get 60 unique
        if legend_count >= LEGEND_COUNT:
            break
        nation_name = rng.choice(nations)
        first_row = conn.execute(
            "SELECT name_value FROM name_pools WHERE name_type='first_male' AND region=? "
            "ORDER BY RANDOM() LIMIT 1",
            (nation_name,),
        ).fetchone()
        last_row = conn.execute(
            "SELECT name_value FROM name_pools WHERE name_type='last' AND region=? "
            "ORDER BY RANDOM() LIMIT 1",
            (nation_name,),
        ).fetchone()
        if not first_row or not last_row:
            continue
        first = first_row[0]
        last = last_row[0]
        key = f"{first}|{last}"
        if key in used_names:
            continue
        used_names.add(key)
        # Generate the retired legend
        nid = conn.execute(
            "SELECT nation_id FROM nations WHERE name=?", (nation_name,)
        ).fetchone()[0]
        # Random career stats
        wins = rng.randint(18, 35)
        losses = rng.randint(3, 12)
        draws = rng.randint(0, 2)
        title_reigns = rng.randint(1, 4)
        # DOB: 40-65 years old
        age_at_retirement = rng.randint(35, 42)
        years_retired = rng.randint(1, 15)
        dob_year = 2026 - age_at_retirement - years_retired
        dob = f"{dob_year}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"
        # Pick a WC + promotion (any)
        wc_row = conn.execute(
            "SELECT weight_class_id FROM weight_classes ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        wc_id = wc_row[0] if wc_row else 1
        # Create the retired fighter
        cur = conn.execute(
            "INSERT INTO fighters (first_name, last_name, nickname, gender, "
            "date_of_birth, birth_nation_id, weight_class_id, "
            "is_active, is_retired, height_cm, reach_cm, stance, handedness, "
            "injury_proneness, weight_cut_difficulty, consistency, "
            "clutch_factor, marketability, fan_friendliness, promo_boost) "
            "VALUES (?, ?, NULL, 'male', ?, ?, ?, 0, 1, ?, ?, 'orthodox', 'right', "
            "?, ?, ?, ?, ?, ?, ?)",
            (first, last, dob, nid, wc_id,
             rng.randint(165, 195), rng.randint(165, 205),
             rng.randint(30, 70), rng.randint(30, 70),
             rng.randint(50, 80), rng.randint(50, 80),
             rng.randint(60, 90), rng.randint(60, 90),
             rng.randint(40, 80)),
        )
        legend_fid = cur.lastrowid
        # Career
        conn.execute(
            "INSERT INTO fighter_career (fighter_id, record_wins, record_losses, "
            "record_draws, win_streak, loss_streak, career_health, potential, "
            "title_reigns) VALUES (?, ?, ?, ?, 0, 0, 50, ?, ?)",
            (legend_fid, wins, losses, draws, rng.randint(60, 85), title_reigns),
        )
        # Hall of Fame row
        inducted_date = (SIM_DATE - timedelta(days=rng.randint(30, 3650))).strftime("%Y-%m-%d")
        # Career summary
        summaries = [
            f"{first} {last} retired as one of the most respected fighters of 'his' era, "
            f"finishing with a {wins}-{losses}-{draws} record and {title_reigns} title reign"
            f"{'s' if title_reigns != 1 else ''}.",
            f"A {nation_name} legend, {first} {last} compiled a {wins}-{losses} record "
            f"over a decorated career that included {title_reigns} championship reign"
            f"{'s' if title_reigns != 1 else ''}.",
            f"{first} {last} was a cornerstone of the sport's growth, finishing "
            f"{wins}-{losses}-{draws} with {title_reigns} title runs.",
        ]
        summary = rng.choice(summaries).replace("'his'", "his")
        # Career highlights
        highlights = []
        if title_reigns >= 1:
            highlights.append(f"{title_reigns}-time champion")
            highlights.append(f"{rng.randint(3, 12)} title defenses")
        if wins >= 25:
            highlights.append(f"{wins} professional wins")
        if wins - losses >= 15:
            highlights.append("Elite win-loss differential")
        highlights.append(f"Hall of Fame inductee {inducted_date[:4]}")
        highlights_str = "\n".join(f"• {h}" for h in highlights)
        conn.execute(
            "INSERT INTO hall_of_fame (fighter_id, inducted_date, career_summary, "
            "career_highlights) VALUES (?, ?, ?, ?)",
            (legend_fid, inducted_date, summary, highlights_str),
        )
        legend_count += 1
    conn.commit()
    print(f"  Hall of Fame legends: {legend_count}")

    # ----------------------------------------------------------------
    # 3. Memory links for champion successors (champion-only per
    #    pre-B1 fix decision). Since this is the initial seed, we
    #    don't have retiring champions yet — skip. Memory links will
    #    be created during gameplay when champions retire.
    # ----------------------------------------------------------------
    print("Memory links: skipped (no retiring champions in initial seed)")

    # ----------------------------------------------------------------
    # 4. Historical news items (~500).
    #    Cover: title wins, upsets, debuts, retirements, milestone wins.
    # ----------------------------------------------------------------
    print("Generating historical news items...")
    # Get or create "System Feed" news source
    src_row = conn.execute(
        "SELECT news_source_id FROM news_sources WHERE name='System Feed'"
    ).fetchone()
    if src_row is None:
        cur = conn.execute(
            "INSERT INTO news_sources (name, credibility, sensationalism, "
            "bias, regional_reach, reliability, frequency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("System Feed", 70, 40, 50, 60, 80, 80),
        )
        src_id = cur.lastrowid
    else:
        src_id = src_row[0]

    n_news = 0
    # a) Title win news — one per current champion
    for champ_id, (defenses, champ_since) in champion_ids.items():
        if champ_since is None:
            continue
        f_row = conn.execute(
            "SELECT first_name, last_name, nickname, weight_class_id, current_promotion_id "
            "FROM fighters WHERE fighter_id=?",
            (champ_id,),
        ).fetchone()
        if f_row is None:
            continue
        first, last, nick, wc_id, promo_id = f_row
        wc_name = conn.execute(
            "SELECT name FROM weight_classes WHERE weight_class_id=?", (wc_id,)
        ).fetchone()[0]
        promo_name = conn.execute(
            "SELECT name FROM promotions WHERE promotion_id=?", (promo_id,)
        ).fetchone()[0] if promo_id else "Alpha Combat Federation"
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"{first} {last} captures {promo_name} {wc_name} title",
             f"{first} {last} {f'\"{nick}\" ' if nick else ''}defied the odds "
             f"to claim the {promo_name} {wc_name} championship. The new champion "
             f"brings an exciting style and a hungry mindset to the title picture.",
             "positive", "title", champ_id, champ_since),
        )
        n_news += 1

    # b) Upset news — 100 random fights where the lower-rated fighter won
    upsets = conn.execute(
        "SELECT f.fight_id, f.winner_fighter_id, f.loser_fighter_id, "
        "f.result_type, f.finish_round, f.event_id, e.event_date, "
        "wf.first_name, wf.last_name, wf.nickname, "
        "lf.first_name, lf.last_name, lf.nickname "
        "FROM fights f "
        "JOIN events e ON e.event_id=f.event_id "
        "JOIN fighters wf ON wf.fighter_id=f.winner_fighter_id "
        "JOIN fighters lf ON lf.fighter_id=f.loser_fighter_id "
        "WHERE f.winner_fighter_id IS NOT NULL "
        "AND f.result_type IN ('ko_tko', 'submission', 'doctor_stoppage') "
        "AND f.finish_round = 1 "
        "ORDER BY RANDOM() LIMIT 100"
    ).fetchall()
    for u in upsets:
        (fight_id, wid, lid, rt, fr, eid, edate,
         wf_first, wf_last, wf_nick, lf_first, lf_last, lf_nick) = u
        rt_label = {"ko_tko": "KO", "submission": "submission",
                    "doctor_stoppage": "doctor stoppage"}.get(rt, rt)
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, fight_id, event_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"{wf_first} {wf_last} stuns {lf_first} {lf_last} with first-round {rt_label}",
             f"In a shocking upset, {wf_first} {wf_last} "
             f"{f'\"{wf_nick}\" ' if wf_nick else ''}finished {lf_first} {lf_last} "
             f"{f'\"{lf_nick}\" ' if lf_nick else ''}in the first round by {rt_label}. "
             f"The upset sends shockwaves through the division.",
             "neutral", "upset", wid, fight_id, eid, edate),
        )
        n_news += 1

    # c) Debut news — 100 random prospects' first fights (fight_id lowest per fighter)
    debut_fights = conn.execute(
        "SELECT fh.fight_id, fh.fighter_id, fh.event_date, "
        "f.first_name, f.last_name, f.nickname "
        "FROM fight_history fh "
        "JOIN fighters f ON f.fighter_id=fh.fighter_id "
        "WHERE fh.fight_id IN ("
        "  SELECT MIN(fight_id) FROM fight_history GROUP BY fighter_id"
        ") "
        "ORDER BY RANDOM() LIMIT 100"
    ).fetchall()
    for d in debut_fights:
        fight_id, fid, edate, first, last, nick = d
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, fight_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"{first} {last} makes professional debut",
             f"{first} {last} {f'\"{nick}\" ' if nick else ''}steps into the cage "
             f"for 'his' first professional fight. The young prospect looks to make "
             f"a statement and start 'his' career with a win.".replace("'his'", "his").replace("'his'", "his"),
             "neutral", "debut", fid, fight_id, edate),
        )
        n_news += 1

    # d) Milestone win news — 100 fighters' 20th win
    milestones = conn.execute(
        "SELECT f.first_name, f.last_name, f.nickname, fh.event_date, fh.fight_id, "
        "fh.fighter_id, fc.record_wins "
        "FROM fight_history fh "
        "JOIN fighters f ON f.fighter_id=fh.fighter_id "
        "JOIN fighter_career fc ON fc.fighter_id=fh.fighter_id "
        "WHERE fc.record_wins >= 20 "
        "AND fh.outcome='win' "
        "ORDER BY RANDOM() LIMIT 100"
    ).fetchall()
    for m in milestones:
        first, last, nick, edate, fight_id, fid, total_wins = m
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, fight_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"{first} {last} notches 20th career win",
             f"{first} {last} {f'\"{nick}\" ' if nick else ''}reached a career "
             f"milestone with 'his' 20th professional victory. The veteran continues "
             f"to add to an impressive resume.".replace("'his'", "his"),
             "positive", "milestone", fid, fight_id, edate),
        )
        n_news += 1

    # e) Retirement news — 50 random veteran fighters (35+) marked as "considering retirement"
    veterans = conn.execute(
        "SELECT fighter_id, first_name, last_name, nickname, date_of_birth "
        "FROM fighters WHERE is_active=1 AND date_of_birth <= '1989-01-01' "
        "ORDER BY RANDOM() LIMIT 50"
    ).fetchall()
    for v in veterans:
        fid, first, last, nick, dob = v
        edate = (SIM_DATE - timedelta(days=rng.randint(1, 30))).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"Veteran {first} {last} reportedly considering retirement",
             f"At {2026 - int(dob[:4])} years old, {first} {last} "
             f"{f'\"{nick}\" ' if nick else ''}is said to be weighing 'his' "
             f"future in the sport. The veteran has had a long, decorated career "
             f"and may be nearing the end.".replace("'his'", "his"),
             "neutral", "retirement", fid, edate),
        )
        n_news += 1

    conn.commit()
    print(f"  News items: {n_news}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("World seed Phase 5 complete.")
    print(f"  Fighter bios:        {n_bios}")
    print(f"  Hall of Fame legends: {legend_count}")
    print(f"  News items:          {n_news}")
    print()
    print("WORLD SEED COMPLETE.")
    print()
    # Final world stats
    print("Final world statistics:")
    for q, label in [
        ("SELECT COUNT(*) FROM nations", "Nations"),
        ("SELECT COUNT(*) FROM regions", "Regions"),
        ("SELECT COUNT(*) FROM cities", "Cities"),
        ("SELECT COUNT(*) FROM venues", "Venues"),
        ("SELECT COUNT(*) FROM weight_classes", "Weight classes"),
        ("SELECT COUNT(*) FROM name_pools", "Name pool entries"),
        ("SELECT COUNT(*) FROM gyms", "Gyms"),
        ("SELECT COUNT(*) FROM promotions", "Promotions"),
        ("SELECT COUNT(*) FROM staff", "Staff"),
        ("SELECT COUNT(*) FROM fighters", "Fighters (active)"),
        ("SELECT COUNT(*) FROM fighters WHERE is_retired=1", "Fighters (retired legends)"),
        ("SELECT COUNT(*) FROM events", "Events (historical)"),
        ("SELECT COUNT(*) FROM fights", "Fights (historical)"),
        ("SELECT COUNT(*) FROM fight_history", "Fight history rows"),
        ("SELECT COUNT(*) FROM titles", "Titles"),
        ("SELECT COUNT(*) FROM contracts", "Contracts"),
        ("SELECT COUNT(*) FROM injuries", "Injuries"),
        ("SELECT COUNT(*) FROM fighter_bios", "Fighter bios"),
        ("SELECT COUNT(*) FROM hall_of_fame", "Hall of Fame inductees"),
        ("SELECT COUNT(*) FROM news_items", "News items"),
    ]:
        n = conn.execute(q).fetchone()[0]
        print(f"  {label}: {n}")
    print("=" * 60)
    print()
    print("The world DB is at data/cage_empire.db.")
    print("The game will load this DB directly — no re-seeding on startup.")
    print()
    print("To reset: python src/build_db.py --fresh (DESTROYS the world)")
    print("To update schema: python src/build_db.py --migrate (preserves world)")

    conn.close()


if __name__ == "__main__":
    main()
