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


def _bio_unproven_prospect(f):
    """Bio for a young fighter with few fights — potential unknown.
    This is the DEFAULT tone for prospects. Crucially, it does NOT
    reveal whether the fighter has elite or limited potential — the
    bio reads the same either way. This preserves the scouting
    challenge: the player has to actually scout (Task 18) or watch
    the fighter fight to learn their ceiling.
    """
    name = f"{f['first_name']} {f['last_name']}"
    if f['nickname']:
        name += f" '{f['nickname']}'"
    wins = f['record_wins']
    losses = f['record_losses']
    total = wins + losses
    variants = [
        f"{name} is {f['age']} years old with a {wins}-{losses} record and everything still to prove. The {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has shown flashes in 'his' early fights, but the sample size is small and the competition hasn't been elite. Whether 'he' develops into a contender or settles into the mid-card is an open question — one that only time and fights will answer.",
        f"Early career. {total} fights. {wins}-{losses}. That's the entire resume for {f['first_name']} {f['last_name']}, a {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} training out of {f['gym_name']}. The tools are there — whether they translate against better opposition is what the next few years will determine. Right now, 'he' is a question mark with potential.",
        f"There's a version of the future where {name} is a champion. There's also a version where 'he' flames out by 25. At {f['age']} with a {wins}-{losses} record, the {_archetype_noun(f['style_archetype_name'])} from {f['gym_name']} is at the career crossroads every young fighter hits — the jump from prospect to contender is the hardest one to make.",
        f"{f['first_name']} {f['last_name']} has the look of a fighter who could go either way. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} is {wins}-{losses} in 'his' young career — not enough data to know if 'he' is a future title challenger or a career gatekeeper. The next few fights will tell us which.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he")


def _bio_mid_carder(f):
    """Bio for a solid-but-unspectacular mid-card fighter. The
    backbone of any promotion — good enough to stick around, not
    good enough to break through.
    """
    name = f"{f['first_name']} {f['last_name']}"
    wins = f['record_wins']
    losses = f['record_losses']
    variants = [
        f"{name} is the kind of fighter who fills out a card and makes the better fighters earn 'their' money. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has put together a {wins}-{losses} record that's good enough to stay employed but not quite good enough to crack the top 15. There's no shame in that — someone has to be the fight before the fight.",
        f"Solid. Dependable. Unspectacular. {f['first_name']} {f['last_name']} is the definition of a mid-card roster filler — and that's not a knock. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} from {f['gym_name']} is {wins}-{losses}, shows up on weight, and gives the prospects a test without embarrassing 'himself'. Every promotion needs fighters like this.",
        f"Not every fighter is a contender. {name} knows that better than anyone. At {f['age']}, the {_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has settled into a role: beat the fighters 'he' should beat, lose to the fighters 'he' shouldn't, and keep the card moving. A {wins}-{losses} record built on that reality.",
    ]
    import random as _r
    return _r.choice(variants).replace("'his'", "his").replace("'him'", "him").replace("'he'", "he").replace("'himself'", "himself").replace("'their'", "their")


def _bio_late_bloomer(f):
    """Bio for an older fighter who's hitting their stride late."""
    name = f"{f['first_name']} {f['last_name']}"
    wins = f['record_wins']
    losses = f['record_losses']
    return (
        f"They said {name} was done. They were wrong. The {f['age']}-year-old "
        f"{_archetype_noun(f['style_archetype_name'])} out of {f['gym_name']} has found "
        f"another gear late in 'his' career, putting together a run that has the division "
        f"re-evaluating what 'he' is capable of. At {wins}-{losses}, the late-career surge "
        f"is real — the question is how far it goes."
    ).replace("'his'", "his").replace("'he'", "he")


def _bio_enforcer(f):
    """Bio for a tough, intimidating fighter who wins through pressure."""
    name = f"{f['first_name']} {f['last_name']}"
    if f['nickname']:
        name += f" '{f['nickname']}'"
    wins = f['record_wins']
    losses = f['record_losses']
    return (
        f"{name} doesn't win pretty. {f['first_name']} wins ugly, wins tired, wins "
        f"through attrition. The {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} "
        f"out of {f['gym_name']} has built a {wins}-{losses} record on the back of pressure, "
        f"toughness, and the kind of relentless forward motion that breaks lesser fighters. "
        f"Style points don't matter when the referee raises your hand."
    )


def _bio_neutral(f):
    """Generic bio tone — used when no other tone fits. Reads as a
    straightforward career summary without revealing potential.
    """
    name = f"{f['first_name']} {f['last_name']}"
    if f['nickname']:
        name += f" '{f['nickname']}'"
    wins = f['record_wins']
    losses = f['record_losses']
    draws = f['record_draws']
    total = wins + losses + draws
    return (
        f"{name} is a {f['age']}-year-old {_archetype_noun(f['style_archetype_name'])} "
        f"out of {f['gym_name']}. With a professional record of {wins}-{losses}"
        f"{f'-{draws}' if draws > 0 else ''} across {total} fights, {f['first_name']} "
        f"has been a steady presence in the {f['weight_class_name']} division. "
        f"The {f['promotion_name']} roster fighter continues to compete against the "
        f"best the division has to offer."
    )


BIO_TEMPLATES = {
    "champion_reign":     _bio_champion_reign,
    "unproven_prospect":  _bio_unproven_prospect,
    "grizzled_veteran":   _bio_grizzled_veteran,
    "fallen_contender":   _bio_fallen_contender,
    "journeyman":         _bio_journeyman,
    "cult_hero":          _bio_cult_hero,
    "mid_carder":         _bio_mid_carder,
    "late_bloomer":       _bio_late_bloomer,
    "enforcer":           _bio_enforcer,
    "neutral":            _bio_neutral,
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
    """Pick the appropriate bio_tone for a fighter based on their stats.

    CRITICAL DESIGN RULE: the bio tone must NOT reveal the fighter's
    hidden `potential` value. A limited-potential prospect and an elite-
    potential prospect get the SAME tone ('unproven_prospect') — the
    bio reads identically either way. This preserves the scouting
    challenge: the player has to actually scout (Task 18) or watch the
    fighter fight to learn their ceiling.

    Tone selection is based on OBSERVABLE career state only:
    - Is the fighter a current champion? → champion_reign
    - Is the fighter young with few fights? → unproven_prospect
    - Is the fighter old with many fights? → grizzled_veteran
    - Is the fighter on a losing streak with a good record? → fallen_contender
    - Is the fighter on a win streak late in career? → late_bloomer
    - Does the fighter have high fan_friendliness? → cult_hero
    - Does the fighter have high aggression + durability? → enforcer
    - Is the fighter mid-career with a .500-ish record? → mid_carder
    - Default → journeyman (if many fights) or neutral (if few)
    """
    total_fights = f['record_wins'] + f['record_losses'] + f['record_draws']

    # Current champion — always champion_reign (observable: they hold a belt)
    if f.get('is_champion'):
        return "champion_reign"

    # Young fighter with few fights — unproven_prospect REGARDLESS of
    # potential. This is the key: an elite 20-year-old and a limited
    # 20-year-old both get 'unproven_prospect'. The bio says "could go
    # either way" — true for both.
    if f['age'] <= 24 and total_fights <= 8:
        return "unproven_prospect"

    # Old fighter with many fights — grizzled_veteran
    if f['age'] >= 36 and total_fights >= 30:
        return "grizzled_veteran"

    # Fallen contender — good record but on a losing streak (observable)
    if f.get('loss_streak', 0) >= 3 and f['record_wins'] >= 10:
        return "fallen_contender"

    # Late bloomer — older fighter on a win streak (observable)
    if f['age'] >= 33 and f.get('win_streak', 0) >= 3:
        return "late_bloomer"

    # Cult hero — high fan_friendliness (observable personality trait)
    if f.get('fan_friendliness', 50) >= 75:
        return "cult_hero"

    # Enforcer — high aggression (observable personality trait)
    if f.get('aggression', 50) >= 75:
        return "enforcer"

    # Mid-carder — mid-career, .500-ish record, not on a streak
    if 25 <= f['age'] <= 35 and total_fights >= 10:
        win_rate = f['record_wins'] / max(1, total_fights)
        if 0.35 <= win_rate <= 0.65:
            return "mid_carder"

    # Journeyman — veteran with many fights, mediocre record
    if total_fights >= 15:
        return "journeyman"

    # Default — neutral (for anyone who doesn't fit above)
    return "neutral"


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
    # 1. Fighter bios for ALL active fighters (not just top 200).
    #
    # CRITICAL: every active fighter gets a bio. The previous approach
    # (top 200 only) created a scouting tell — the player could identify
    # "featured" fighters by the presence of a bio. Now all 4000 active
    # fighters + 60 retired legends get one.
    #
    # The bio TONE is selected based on OBSERVABLE career state only
    # (champion, age, record, streaks, fan_friendliness, aggression).
    # It NEVER reveals the fighter's hidden `potential` — a limited-
    # potential prospect and an elite-potential prospect both get
    # 'unproven_prospect' with identical bio text. This preserves the
    # scouting challenge per the user's directive.
    # ----------------------------------------------------------------
    print("Generating fighter bios for ALL active fighters...")

    # Get current champions
    champions = conn.execute(
        "SELECT t.current_champion_fighter_id, t.title_defenses_count, "
        "t.champion_since_date "
        "FROM titles t WHERE t.current_champion_fighter_id IS NOT NULL"
    ).fetchall()
    champion_ids = {r[0]: (r[1], r[2]) for r in champions}

    # Get ALL active fighters (not just top 200)
    all_fighters = conn.execute(
        "SELECT f.fighter_id, f.first_name, f.last_name, f.nickname, "
        "f.gender, f.date_of_birth, f.fight_style_archetype_id, "
        "f.current_gym_id, f.current_promotion_id, f.weight_class_id, "
        "f.marketability, f.fan_friendliness, "
        "fc.record_wins, fc.record_losses, fc.record_draws, "
        "fc.win_streak, fc.loss_streak, fc.potential, fc.title_reigns, "
        "r.rating, sa.name AS style_archetype_name, "
        "wc.name AS weight_class_name, p.name AS promotion_name, "
        "g.name AS gym_name, fp.aggression "
        "FROM fighters f "
        "JOIN fighter_career fc ON fc.fighter_id=f.fighter_id "
        "LEFT JOIN rankings r ON r.fighter_id=f.fighter_id "
        "LEFT JOIN style_archetypes sa ON sa.style_archetype_id=f.fight_style_archetype_id "
        "LEFT JOIN weight_classes wc ON wc.weight_class_id=f.weight_class_id "
        "LEFT JOIN promotions p ON p.promotion_id=f.current_promotion_id "
        "LEFT JOIN gyms g ON g.gym_id=f.current_gym_id "
        "LEFT JOIN fighter_personality fp ON fp.fighter_id=f.fighter_id "
        "WHERE f.is_retired = 0"
    ).fetchall()

    n_bios = 0
    n_bios_skipped = 0  # Fix 1.1: fighters that already have a bio (supervisor's originals)
    BATCH = 500
    for row in all_fighters:
        (fid, first, last, nick, gender, dob, sa_id, gym_id, promo_id, wc_id,
         market, fan_friend, w, l, d, ws, ls, pot, reigns, rating,
         sa_name, wc_name, promo_name, gym_name, aggression) = row

        # ------------------------------------------------------------
        # Fix 1.1: Only generate a bio for fighters that don't already
        # have one. The supervisor's 4000 original bios were saved in
        # seed_world_phase3_from_profiles.py (from parsed_fighters.json).
        # Skipping them here preserves the supervisor's per-fighter
        # voice verbatim — no template substitution overwrites them.
        # Fighters without a bio row (regen replacements, etc.) still
        # get a template-generated one below.
        # ------------------------------------------------------------
        existing_bio = conn.execute(
            "SELECT bio_text FROM fighter_bios WHERE fighter_id=?",
            (fid,),
        ).fetchone()
        if existing_bio and existing_bio[0]:
            n_bios_skipped += 1
            continue

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
            'gym_name': gym_name or 'an independent camp',
            'fan_friendliness': fan_friend or 50,
            'marketability': market or 50,
            'aggression': aggression or 50,
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
        if n_bios % BATCH == 0:
            conn.commit()
            print(f"  ...{n_bios} bios generated")
    conn.commit()
    print(f"  Fighter bios: {n_bios} generated (+{n_bios_skipped} skipped — supervisor originals preserved per Fix 1.1)")

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
        # Career summary — 8 variants for variety
        summaries = [
            f"{first} {last} retired as one of the most respected fighters of his era, "
            f"finishing with a {wins}-{losses}-{draws} record and {title_reigns} title reign"
            f"{'s' if title_reigns != 1 else ''}.",
            f"A {nation_name} legend, {first} {last} compiled a {wins}-{losses} record "
            f"over a decorated career that included {title_reigns} championship reign"
            f"{'s' if title_reigns != 1 else ''}.",
            f"Over a career spanning {wins + losses + draws} fights, {first} {last} "
            f"established himself as one of the sport's most consistent competitors, "
            f"capturing {title_reigns} title{'s' if title_reigns != 1 else ''} along the way.",
            f"The {nation_name}-born {first} {last} walked away from the sport with a "
            f"{wins}-{losses}-{draws} record and a legacy built on {title_reigns} title run"
            f"{'s' if title_reigns != 1 else ''}.",
            f"{first} {last}'s name was synonymous with excellence in the cage. The "
            f"{nation_name} veteran retired at {wins}-{losses}-{draws} with {title_reigns} "
            f"championship reign{'s' if title_reigns != 1 else ''} to his credit.",
            f"Few fighters embodied their nation's fighting spirit like {first} {last}. "
            f"The {nation_name} icon finished {wins}-{losses}-{draws} with {title_reigns} "
            f"title reign{'s' if title_reigns != 1 else ''} in a career that inspired a generation.",
            f"{first} {last} didn't just fight — he defined an era. The {nation_name} star "
            f"hung up the gloves at {wins}-{losses}-{draws} with {title_reigns} championship "
            f"reign{'s' if title_reigns != 1 else ''}, cementing his place among the greats.",
            f"From {nation_name} to the top of the sport, {first} {last}'s journey ended "
            f"with a {wins}-{losses}-{draws} record and {title_reigns} title reign"
            f"{'s' if title_reigns != 1 else ''}. The kind of career that gets remembered.",
        ]
        summary = rng.choice(summaries)
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

    # d) Milestone win news — 100 fighters' "20th" win.
    # v2.10.0 (FIX-VoiceRep, §14): the OLD headline/body used raw
    # "20th" / "20" digit characters — a §14 violation (no raw
    # numbers in player-facing text). Replaced with the word form
    # "twentieth" so the seed-time news is digit-free.
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
             f"{first} {last} notches twentieth career win",
             f"{first} {last} {f'\"{nick}\" ' if nick else ''}reached a career "
             f"milestone with 'his' twentieth professional victory. The veteran continues "
             f"to add to an impressive resume.".replace("'his'", "his"),
             "positive", "milestone", fid, fight_id, edate),
        )
        n_news += 1

    # e) Retirement news — 50 random veteran fighters (35+) marked as "considering retirement"
    # v2.10.0 (FIX-VoiceRep, §14): the OLD body used raw age digit
    # characters ("At 42 years old..."). Replaced with the word-form
    # age phrase so the seed-time news is digit-free.
    veterans = conn.execute(
        "SELECT fighter_id, first_name, last_name, nickname, date_of_birth "
        "FROM fighters WHERE is_active=1 AND date_of_birth <= '1989-01-01' "
        "ORDER BY RANDOM() LIMIT 50"
    ).fetchall()
    for v in veterans:
        fid, first, last, nick, dob = v
        edate = (SIM_DATE - timedelta(days=rng.randint(1, 30))).strftime("%Y-%m-%d")
        # v2.10.0 (FIX-VoiceRep, §14): OLD body used raw age digit
        # ("At 42 years old..."). Replaced with an age-band phrase
        # ("nearing forty" / "past forty" / "in his late thirties")
        # so the seed-time news is digit-free. The bands map roughly
        # to the same retirement-eligibility thresholds used by
        # tick_processor._check_retirements (40 + declining health,
        # 45 mandatory).
        _age_num = 2026 - int(dob[:4])
        if _age_num >= 43:
            _age_phrase = "past forty"
        elif _age_num >= 40:
            _age_phrase = "nearing forty"
        elif _age_num >= 35:
            _age_phrase = "in his late thirties"
        else:
            _age_phrase = "a veteran fighter"
        conn.execute(
            "INSERT INTO news_items (news_source_id, headline, body, "
            "sentiment, topic, fighter_id, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (src_id,
             f"Veteran {first} {last} reportedly considering retirement",
             f"At {_age_phrase}, {first} {last} "
             f"{f'\"{nick}\" ' if nick else ''}is said to be weighing 'his' "
             f"future in the sport. The veteran has had a long, decorated career "
             f"and may be nearing the end.".replace("'his'", "his"),
             "neutral", "retirement", fid, edate),
        )
        n_news += 1

    conn.commit()
    print(f"  News items: {n_news}")

    # ----------------------------------------------------------------
    # Phase B (B2): Seed-time social posts.
    #
    # Per docs/FULL_BUILD_AUDIT.md §3 ("The world seed doesn't
    # generate any social_posts. The table is empty until the player
    # starts resolving fights. Should have seed-time posts") and the
    # Phase B brief, generate ~100-200 seed-time social posts so the
    # social feed feels lived-in from day 1. Three flavors:
    #
    #   1. Rivalry-driven (callout / trash_talk): for each ACTIVE
    #      rivalry, generate 1-2 posts between the rivals. The post
    #      type is rng-picked between 'callout' and 'trash_talk'
    #      (weighted toward 'callout' since that's the more natural
    #      "I want the rematch" beat). Uses social.generate_post so
    #      the post_text uses voice-layer descriptors (§14).
    #   2. Champion brag: for each current champion, generate 1 'brag'
    #      post. Champions brag — they hold the belt.
    #   3. Prospect hype: for top prospects (elite potential, age <
    #      24), generate 1 'hype' post. Prospects are hyped — the
    #      future is bright.
    #
    # All posts use the sim clock's current_date as post_date so they
    # appear as "recent" in the social feed. The generate_post
    # function handles the voice-layer descriptor rendering, the
    # engagement computation, and the beef-escalation flagging.
    # ----------------------------------------------------------------
    print("Generating seed-time social posts...")
    import sys as _sys_social
    _sys_social.path.insert(0, str(PROJECT_DIR / "src"))
    import social as _social

    rng_social = random.Random(20260725 + 1)  # distinct from main phase5 RNG
    sim_date_str = SIM_DATE.strftime("%Y-%m-%d")
    n_posts = 0
    n_rivalry_posts = 0
    n_champ_posts = 0
    n_prospect_posts = 0

    # Skip if Phase 5 social posts already seeded (idempotent — if
    # the social_posts table already has rows, we assume the seed
    # ran OR in-game ticks have added posts; either way, we don't
    # want to stack duplicates on top).
    existing_posts = conn.execute(
        "SELECT COUNT(*) FROM social_posts"
    ).fetchone()[0]
    if existing_posts > 0:
        print(f"  Already {existing_posts} social_posts — skipping seed-time social post generation.")
    else:
        # ----- 1. Rivalry-driven posts -------------------------------
        # Iterate all active rivalries. For each, generate 1-2 posts
        # between the two fighters. The post_type is rng-picked
        # between 'callout' (weight 3) and 'trash_talk' (weight 2).
        # The poster is rng-picked between fighter_a and fighter_b
        # (with the target being the other). This seeds a realistic
        # mix of "I want the rematch" callouts and "you got lucky"
        # trash talk.
        active_rivalries = conn.execute(
            "SELECT rivalry_id, fighter_a_id, fighter_b_id, "
            "rivalry_type, rivalry_heat "
            "FROM rivalries WHERE is_active=1"
        ).fetchall()
        for (riv_id, a_id, b_id, rtype, heat) in active_rivalries:
            # 1-2 posts per rivalry (higher heat → more likely 2).
            n_for_this = 2 if (heat >= 70 or rng_social.random() < 0.5) else 1
            for _ in range(n_for_this):
                # Pick poster + target.
                if rng_social.random() < 0.5:
                    poster, target = a_id, b_id
                else:
                    poster, target = b_id, a_id
                # Pick post type.
                post_type = rng_social.choices(
                    ["callout", "trash_talk"], weights=[3, 2], k=1,
                )[0]
                # Pick a post_date in the recent past (1-30 days ago)
                # so the feed shows a mix of "today" and "last week"
                # posts (a fresh feed with all today-dated posts would
                # look artificial).
                days_ago = rng_social.randint(0, 30)
                post_date = (SIM_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                try:
                    post_id = _social.generate_post(
                        conn, poster, post_type,
                        target_fighter_id=target,
                        post_date=post_date, rng=rng_social,
                        bypass_cooldown=True,  # seed-time — no cooldown
                    )
                    if post_id is not None:
                        n_posts += 1
                        n_rivalry_posts += 1
                except Exception as e:
                    # Defensive — a single failed post shouldn't kill
                    # the seed. Log and continue.
                    print(f"    WARN: rivalry post failed for {poster}->{target}: {e}")

        # ----- 2. Champion brag posts -------------------------------
        # For each current champion, generate 1 'brag' post. Champions
        # brag — they hold the belt. No target_fighter_id (a brag is
        # a general "I'm the champ" post, not aimed at a specific
        # rival).
        champions = conn.execute(
            "SELECT t.current_champion_fighter_id "
            "FROM titles t "
            "WHERE t.current_champion_fighter_id IS NOT NULL "
            "AND t.is_vacant = 0"
        ).fetchall()
        for (champ_id,) in champions:
            days_ago = rng_social.randint(0, 14)
            post_date = (SIM_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            try:
                post_id = _social.generate_post(
                    conn, champ_id, "brag",
                    post_date=post_date, rng=rng_social,
                    bypass_cooldown=True,
                )
                if post_id is not None:
                    n_posts += 1
                    n_champ_posts += 1
            except Exception as e:
                print(f"    WARN: champ brag post failed for {champ_id}: {e}")

        # ----- 3. Prospect hype posts -------------------------------
        # For top prospects (elite potential, age < 24), generate 1
        # 'hype' post. "Elite potential" maps to the voice.py tier
        # 'elite' (potential >= 90). The brief says "top prospects
        # (elite potential, age < 24)". We use the sim_date to
        # compute age from date_of_birth (same as the bio tone picker).
        prospects = conn.execute(
            "SELECT f.fighter_id, f.date_of_birth "
            "FROM fighters f "
            "JOIN fighter_career fc ON fc.fighter_id = f.fighter_id "
            "WHERE f.is_active = 1 AND f.is_retired = 0 "
            "AND fc.potential >= 90 "
            "AND f.current_promotion_id IS NOT NULL"
        ).fetchall()
        for (fid, dob) in prospects:
            # Compute age.
            try:
                dob_dt = datetime.strptime(dob, "%Y-%m-%d")
                age = (SIM_DATE - dob_dt).days // 365
            except (ValueError, TypeError):
                continue
            if age >= 24:
                continue
            days_ago = rng_social.randint(0, 21)
            post_date = (SIM_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            try:
                post_id = _social.generate_post(
                    conn, fid, "hype",
                    post_date=post_date, rng=rng_social,
                    bypass_cooldown=True,
                )
                if post_id is not None:
                    n_posts += 1
                    n_prospect_posts += 1
            except Exception as e:
                print(f"    WARN: prospect hype post failed for {fid}: {e}")

        conn.commit()
        print(f"  Social posts:        {n_posts}")
        print(f"    rivalry-driven:    {n_rivalry_posts}")
        print(f"    champion brags:    {n_champ_posts}")
        print(f"    prospect hype:     {n_prospect_posts}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("World seed Phase 5 complete.")
    print(f"  Fighter bios:        {n_bios}")
    print(f"  Hall of Fame legends: {legend_count}")
    print(f"  News items:          {n_news}")
    if 'n_posts' in locals():
        print(f"  Seed-time social posts: {n_posts}")

    # ----------------------------------------------------------------
    # v2.9.0 (Task 19): populate fighter_descriptors snapshots for
    # ALL active fighters. The snapshot is normally updated on trigger
    # events (camp, fight, injury), but the seed needs an initial
    # population so the UI can display descriptors immediately.
    # ----------------------------------------------------------------
    print()
    print("Populating descriptor snapshots for all active fighters...")
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_DIR / "src"))
    import app as _app
    all_fids = conn.execute(
        "SELECT fighter_id FROM fighters WHERE is_retired=0"
    ).fetchall()
    n_snaps = 0
    for (fid,) in all_fids:
        _app.update_fighter_descriptor_snapshot(conn, fid)
        n_snaps += 1
        if n_snaps % 500 == 0:
            conn.commit()
            print(f"  ...{n_snaps} snapshots")
    conn.commit()
    print(f"  Descriptor snapshots: {n_snaps}")

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
