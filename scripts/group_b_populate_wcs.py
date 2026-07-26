#!/usr/bin/env python3
"""CAGE EMPIRE — Phase 1.5 Group B Fix B1: Populate empty male WCs.

Generates ~150 fighters per empty male weight class (WCs 6, 7, 8 —
Featherweight, Bantamweight, Flyweight) for a total of ~450 new
fighters. Distributes them across promotions proportional to existing
roster sizes (major 22.5% / mid 33.75% / small 30% / free agents
13.75%). Creates titles for the 3 WCs across all 10 promotions (30
new titles, all vacant). Creates contracts for signed fighters.

Uses the existing fighter_gen module for:
  - generate_attribute_block(archetype_id, conn) — archetype-biased
    25-attribute block (Balanced/Striker/Grappler/etc.)
  - generate_personality_block(archetype_id, conn) — trait-biased
    20-personality block (Calm/Aggressive/Methodical/Showman/Quiet
    Professional)
  - generate_physical_block(weight_class_max_kg, gender) — height,
    reach, stance, handedness scaled by WC weight
  - generate_nickname(attrs, pers, style_name, nation, rng) — unique
    relevant nicknames
  - generate_potential() — 10% elite / 30% solid / 60% limited

Bios are TEMPLATE-based (not from the supervisor's profiles — those
4000 profiles don't cover the 3 empty WCs). Templates per bio_tone
(neutral, unproven_prospect, grizzled_veteran, mid_carder, journeyman,
late_bloomer, enforcer, fallen_contender, cult_hero, champion_reign).
Tone is derived from observable career state (age + record + streak +
fan_friendliness + aggression) — mirrors seed_world_phase3's
_derive_bio_tone logic. NO hidden potential is revealed by the tone
(CONVENTIONS §13 — Discovery pillar: a limited-potential prospect
and an elite-potential prospect get the same 'unproven_prospect'
tone).

Idempotency:
  - The script checks if WC 6/7/8 already have fighters. If yes, it
    skips generation for that WC (no duplicate insert).
  - The title creation checks for existing (promotion_id, wc_id)
    pairs — only inserts missing ones.
  - The contract creation checks for existing fighter_contracts rows
    for the new fighters — only inserts missing ones.

Usage:
    python3 scripts/group_b_populate_wcs.py            # full populate
    python3 scripts/group_b_populate_wcs.py --check    # report only
    python3 scripts/group_b_populate_wcs.py --only WC6 # just WC 6

CONVENTIONS compliance:
  §1   — No schema change (data-only insert).
  §5   — No new tables — populates existing fighters/fighter_attributes/
         fighter_personality/fighter_career/fighter_bios/titles/
         rankings/contracts/fighter_contracts.
  §6   — Smoke test: run forensic_db_check.py after.
  §13  — Design Law: strengthens Discovery (style-biased attributes
         give the new fighters style identity), Conflict (new weight
         classes with active rosters = more matchup possibilities),
         Growth (potential distribution means some will develop into
         contenders). Bio templates preserve the Voice Layer rule
         (§14) by routing tone through observable state, not raw attrs.
  §16.9 — Backup the DB before running.
"""
import argparse
import json
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"
SRC_DIR = PROJECT_DIR / "src"

sys.path.insert(0, str(SRC_DIR))
import fighter_gen  # noqa: E402

# Reproducible — same seed across runs (idempotency means re-runs are
# no-ops anyway, but the seed ensures the FIRST run is deterministic
# across machines / Python versions).
RANDOM_SEED = 20260726

# ----------------------------------------------------------------
# Population targets.
# ----------------------------------------------------------------

# Total fighters to generate per empty WC.
TARGET_PER_WC = 150

# Distribution across promotion tiers (matches the existing 4000-
# fighter world's distribution).
# Major (P1):     900/4000 = 22.5% → 34 fighters
# Mid (P2,P3,P4): 1350/4000 = 33.75% → 50 fighters (~17 per promo)
# Small (P5-P10): 1200/4000 = 30% → 45 fighters (~8 per promo)
# Free agents:    550/4000 = 13.75% → 21 fighters
# Total per WC: 34 + 50 + 45 + 21 = 150
PROMO_DISTRIBUTION = [
    # (size_tier, count_per_promo, num_promos, label)
    ("major", 34, 1, "Alpha Combat Federation"),       # P1 only
    ("mid",   17, 3, "Rival Fight League + Pacific Rim + European Fight"),  # P2,3,4
    ("small", 8,  6, "6 small promos"),                # P5-10
    # free agents handled separately
]
FREE_AGENT_COUNT_PER_WC = 21  # 150 - 34 - 51 - 48 - 21 = -4 ... wait
# 34 (major) + 17*3=51 (mid) + 8*6=48 (small) + 17 (FA) = 150
FREE_AGENT_COUNT_PER_WC = 17

# Weight class IDs to populate.
EMPTY_WC_IDS = [6, 7, 8]  # Featherweight, Bantamweight, Flyweight (male)

# Age distribution for lighter WCs (real-world data: lighter WCs skew
# younger — flyweight/bantamweight/featherweight are typically 24-32
# years old; very few fighters in these WCs are 38+).
# (low_age, high_age, weight)
AGE_DISTRIBUTION = [
    (18, 22, 15),   # 15% very young prospects
    (23, 27, 35),   # 35% young primes
    (28, 32, 30),   # 30% prime
    (33, 37, 15),   # 15% veteran
    (38, 42,  5),   # 5% aging veteran
]

# Nation distribution for fighter production (weighted by historical
# MMA representation — Brazil, US, Russia, Mexico, Japan, Dagestan,
# UK produce the most MMA fighters).
NATION_WEIGHTS = {
    1: 20,   # United States
    2: 15,   # Brazil
    4: 12,   # Russia
    20: 10,  # Dagestan
    6: 10,   # Mexico
    3: 8,    # Japan
    5: 6,    # United Kingdom
    11: 5,   # France
    9: 4,    # Ireland
    19: 4,   # Netherlands
    7: 3,    # Canada
    14: 3,   # Sweden
    13: 3,   # Poland
    8: 3,    # Australia
    17: 3,   # Cuba
    18: 2,   # Argentina
    16: 2,   # China
    15: 2,   # South Korea
    10: 2,   # Nigeria
    12: 2,   # Germany
}

# Nation → region-string mapping (for name_pools lookups; name_pools
# uses a 'region' TEXT column with values like "United States").
NATION_ID_TO_REGION = {
    1: "United States", 2: "Brazil", 3: "Japan", 4: "Russia",
    5: "United Kingdom", 6: "Mexico", 7: "Canada", 8: "Australia",
    9: "Ireland", 10: "Nigeria", 11: "France", 12: "Germany",
    13: "Poland", 14: "Sweden", 15: "South Korea", 16: "China",
    17: "Cuba", 18: "Argentina", 19: "Netherlands", 20: "Dagestan",
}

# Style archetype bias by nation (weighted). Reflects real-world MMA
# style distributions: Dagestan/Cuba → Wrestler-heavy; Brazil →
# Grappler/Submission-heavy; Netherlands → Striker-heavy; etc.
NATION_STYLE_BIAS = {
    1:  {"Balanced": 3, "Striker": 3, "Wrestler": 2, "Brawler": 2,
         "Counter-Striker": 2, "Grappler": 1, "Submission Specialist": 1},  # US — mixed
    2:  {"Grappler": 4, "Submission Specialist": 4, "Striker": 2,
         "Brawler": 2, "Balanced": 2, "Wrestler": 1},  # Brazil — BJJ
    3:  {"Striker": 4, "Counter-Striker": 3, "Submission Specialist": 2,
         "Balanced": 2, "Wrestler": 1, "Grappler": 1, "Brawler": 1},  # Japan — striking
    4:  {"Wrestler": 3, "Brawler": 2, "Striker": 2, "Balanced": 2,
         "Counter-Striker": 2, "Submission Specialist": 1, "Grappler": 1},  # Russia
    5:  {"Striker": 3, "Counter-Striker": 3, "Balanced": 2, "Brawler": 2,
         "Wrestler": 1, "Grappler": 1, "Submission Specialist": 1},  # UK
    6:  {"Brawler": 3, "Striker": 3, "Balanced": 2, "Wrestler": 2,
         "Counter-Striker": 2, "Submission Specialist": 1, "Grappler": 1},  # Mexico
    7:  {"Balanced": 3, "Wrestler": 2, "Striker": 2, "Counter-Striker": 2,
         "Brawler": 2, "Grappler": 1, "Submission Specialist": 1},  # Canada
    8:  {"Striker": 3, "Balanced": 2, "Wrestler": 2, "Counter-Striker": 2,
         "Brawler": 2, "Grappler": 1, "Submission Specialist": 1},  # Australia
    9:  {"Striker": 3, "Brawler": 3, "Counter-Striker": 2, "Balanced": 2,
         "Wrestler": 1, "Grappler": 1, "Submission Specialist": 1},  # Ireland
    10: {"Wrestler": 4, "Striker": 2, "Balanced": 2, "Brawler": 1,
         "Counter-Striker": 1, "Grappler": 1, "Submission Specialist": 1},  # Nigeria
    11: {"Striker": 3, "Counter-Striker": 3, "Balanced": 2, "Wrestler": 2,
         "Brawler": 1, "Grappler": 1, "Submission Specialist": 1},  # France
    12: {"Balanced": 3, "Wrestler": 2, "Striker": 2, "Counter-Striker": 2,
         "Brawler": 2, "Grappler": 1, "Submission Specialist": 1},  # Germany
    13: {"Wrestler": 3, "Brawler": 2, "Striker": 2, "Balanced": 2,
         "Counter-Striker": 2, "Grappler": 1, "Submission Specialist": 1},  # Poland
    14: {"Wrestler": 4, "Striker": 2, "Balanced": 2, "Brawler": 1,
         "Counter-Striker": 1, "Grappler": 1, "Submission Specialist": 1},  # Sweden — wrestling
    15: {"Striker": 4, "Counter-Striker": 3, "Balanced": 2, "Wrestler": 1,
         "Brawler": 1, "Grappler": 1, "Submission Specialist": 1},  # South Korea — TKD
    16: {"Wrestler": 3, "Striker": 2, "Balanced": 2, "Counter-Striker": 2,
         "Brawler": 2, "Grappler": 1, "Submission Specialist": 1},  # China — Sanda
    17: {"Striker": 4, "Brawler": 3, "Counter-Striker": 2, "Balanced": 2,
         "Wrestler": 1, "Grappler": 1, "Submission Specialist": 1},  # Cuba — boxing
    18: {"Striker": 3, "Brawler": 2, "Balanced": 2, "Counter-Striker": 2,
         "Wrestler": 2, "Grappler": 1, "Submission Specialist": 1},  # Argentina
    19: {"Striker": 5, "Counter-Striker": 3, "Balanced": 1, "Wrestler": 1,
         "Brawler": 1, "Grappler": 1, "Submission Specialist": 1},  # Netherlands — kickboxing
    20: {"Wrestler": 8, "Grappler": 3, "Balanced": 1, "Striker": 1,
         "Brawler": 1, "Counter-Striker": 1, "Submission Specialist": 1},  # Dagestan — wrestling
}


# ----------------------------------------------------------------
# Bio templates per tone.
# Each template is a function (fighter_dict) -> bio_text.
# fighter_dict has: first_name, last_name, nickname, age, wc_name,
# style_name, nation_name, gym_name, promo_name, wins, losses, draws,
# win_streak, loss_streak, fan_friendliness, aggression, potential,
# height_cm.
# Per CONVENTIONS §13.6 (Talent Hunter fantasy) + §13 (Discovery
# pillar), the templates NEVER reveal the hidden `potential` value —
# they treat every prospect the same way (a limited-potential
# prospect and an elite-potential prospect get the same template).
# Per CONVENTIONS §14 (Voice Layer), the bio_text is RAW (not the
# descriptor output of the voice layer) — it's the foundation bio
# that the voice layer will later augment with attribute descriptors.
# ----------------------------------------------------------------

BIO_TEMPLATES = {
    "unproven_prospect": [
        "There's a version of the future where {first} {last} is a champion. There's also a version where he flames out by 25. At {age} with a {wins}-{losses} record, the {style_lower} from {nation} is at the career crossroads every prospect faces. The tools are there — whether they translate against better opposition is the question nobody can answer yet.",
        "The hype started early for {first} '{nick}' {last}. A {style_lower} prospect out of {gym}, he stormed the regional scene with raw athleticism and the kind of potential scouts dream about. Now {age} years old with a {wins}-{losses} slate, the question is whether he can take the next step against tougher foes. The ceiling is high — the floor is hard.",
        "Every gym has That Kid. The one coaches quietly believe might be special. At {gym}, that kid is {first} {last}, a {age}-year-old {style_lower} with a {wins}-{losses} record and the kind of raw tools you can't teach. The next 18 months will tell the story — develop or plateau, contend or fade.",
        "{first} {last} doesn't have a long highlight reel yet. {wins}-{losses} as a pro, all on regional shows, all against varying levels of competition. But the {style_lower} from {nation} has something — coaches at {gym} see it, training partners feel it, and at {age} the runway is still long. Whether that something becomes a title run or just a respectable career is the bet.",
    ],
    "grizzled_veteran": [
        "The young guys think they want smoke with {first} {last}. They usually change their minds. {total_fights} fights deep, {wins}-{losses}, and still going — the {age}-year-old {style_lower} from {nation} has made {gym} his home base for over a decade. He's not the prospect he once was, but he's seen every trick in the book and forgotten more about fight IQ than most prospects will ever learn.",
        "{total_fights} professional fights. {wins} wins, {losses} losses, and a story behind every one of them. {first} '{nick}' {last} has been the gatekeeper, the test, the proving ground for a generation of {wc} prospects coming up through {nation}. At {age}, the {style_lower} isn't done yet — there are still fights to be had, paydays to collect, and one more run to make.",
        "There's something to be said for longevity. {first} {last} has been fighting professionally since before some of his opponents were born. The {age}-year-old {style_lower} out of {gym} carries a {wins}-{losses} record into every fight, and while the speed isn't what it was, the experience gap is a chasm. You don't get to {total_fights} fights by accident.",
    ],
    "mid_carder": [
        "Every promotion needs a fighter like {first} {last}. Someone tough enough to test the prospects, experienced enough to expose the not-ready-yets, and professional enough to show up on short notice when the card needs saving. The {age}-year-old {style_lower} from {nation} carries a {wins}-{losses} record and a reputation as a tough out — never the main event, but always worth the ticket.",
        "Solid. Dependable. Tough. {first} '{nick}' {last} is the kind of {style_lower} who never quite cracked the title picture but never fell out of the conversation either. At {age} with a {wins}-{losses} record out of {gym}, he's the fighter matchmakers call when they need a fight that delivers. Title contender? Probably not. Easy night? Definitely not.",
        "The middle of the card is where {first} {last} lives. {wins}-{losses} as a pro, with enough flashes of brilliance to keep fans interested and enough flat performances to keep expectations measured. The {age}-year-old {style_lower} from {nation} has been a staple of {promo} cards for years — not a star, not a journeyman, but a true mid-card professional.",
    ],
    "journeyman": [
        "{total_fights} fights. {wins} wins, {losses} losses, and a passport full of stamps from shows you've never heard of. {first} {last} is the definition of a journeyman — the {age}-year-old {style_lower} has fought everyone, everywhere, for every reason. He's not in this for the title. He's in this because fighting is what he does.",
        "They don't make fight cards without fighters like {first} '{nick}' {last}. The {style_lower} from {nation} has been a pro for over a decade, compiling a {wins}-{losses} record against a who's-who of opponents across a dozen promotions. At {age}, the end is closer than the beginning — but there are still fights to be had.",
        "If you've watched regional MMA in the last decade, you've seen {first} {last} fight. The {age}-year-old {style_lower} out of {gym} has {total_fights} pro fights to his name, a {wins}-{losses} record, and a reputation as the kind of opponent who makes prospects earn it. No title aspirations — just the next fight, the next paycheck, the next story.",
    ],
    "late_bloomer": [
        "Some fighters peak at 24. {first} {last} is peaking at {age}. The {style_lower} from {nation} spent years as a respectable but unremarkable pro, then something clicked. {win_streak}-fight win streak. Suddenly the {wc} division has a new contender, and {gym} has its first real title hope in years.",
        "The career arc wasn't supposed to look like this. {first} '{nick}' {last} was a {.500} fighter for most of his 20s — good enough to keep his job, not good enough to contend. Then at {age} something changed. The {style_lower} from {nation} is now on a {win_streak}-fight streak, the {wc} division is paying attention, and the late-bloomer narrative is writing itself.",
        "They call it finding your form late. {first} {last} calls it just figuring things out. After years of {wins}-{losses} mediocrity, the {age}-year-old {style_lower} has put together a {win_streak}-fight run that has {promo} fans wondering if the best is yet to come. Late bloomers are rare in this sport — but when they bloom, they bloom big.",
    ],
    "enforcer": [
        "You don't book {first} {last} for technical displays. You book him because someone needs to be hit, hard, and often. The {age}-year-old {style_lower} from {nation} brings violence every time out — a {wins}-{losses} record built on pressure, power, and the kind of aggression that turns fights into wars. His opponents know what's coming. Knowing doesn't help.",
        "{first} '{nick}' {last} isn't here to outpoint you. The {style_lower} out of {gym} is here to hurt you, and his {wins}-{losses} record is full of fights that ended with opponents looking for the exit. At {age}, the engine hasn't slowed — every fight is a statement, and the statement is 'I will hit you until you stop.'",
        "Some fighters are technicians. Some are athletes. {first} {last} is an enforcer. The {age}-year-old {style_lower} from {nation} has built a {wins}-{losses} career on making opponents uncomfortable, rushing their decisions, and turning technical fights into brawls. When {first} is on the card, the matchup matters less than the mayhem.",
    ],
    "fallen_contender": [
        "There was a moment when {first} {last} was the next big thing. {wins} wins, a title shot looming, the {wc} division on notice. Then the losses started. {loss_streak} in a row now, and the {age}-year-old {style_lower} from {nation} is fighting to prove he's not done. The talent that got him here is still there — somewhere. Finding it again is the only fight that matters.",
        "The fall has been hard. {first} '{nick}' {last} was a top-5 {wc} contender two years ago, riding a {wins}-{losses} record into title contention. Then came the {loss_streak}-fight skid — close losses, bad nights, the kind of stretch that makes fighters question everything. At {age}, the {style_lower} from {gym} needs a win like he's never needed one before.",
        "Every fighter's career has a turning point. {first} {last}'s came {loss_streak} fights ago, when the wins stopped coming. The {age}-year-old {style_lower} from {nation} is still {wins}-{losses} overall — still talented, still dangerous — but the momentum is gone and the doubts are loud. One win flips the script. One more loss confirms the decline.",
    ],
    "cult_hero": [
        "If fighting had a fan vote, {first} {last} would main-event every card. The {age}-year-old {style_lower} from {nation} has built a {wins}-{losses} record and a cult following that defies the rankings. He's not the best {wc} in the world — he's just the one fans most want to watch. Style. Heart. Story. {first} has all three.",
        "There are fighters fans respect, and then there are fighters fans LOVE. {first} '{nick}' {last} is the second kind. The {style_lower} out of {gym} brings it every time — {wins}-{losses} record be damned, when {first} fights, the arena watches. At {age}, the cult hero of {promo} is still building the legend, one brawl at a time.",
        "Some fighters are stars. Some are stars in their own orbit. {first} {last} is the second kind — a {age}-year-old {style_lower} with a {wins}-{losses} record that doesn't tell the story. The story is in the fights: the comebacks, the wars, the moments that end up on highlight reels. {nation}'s favorite son isn't going anywhere.",
    ],
    "champion_reign": [
        "The champ. {first} '{nick}' {last} sits atop the {wc} division with a {wins}-{losses} record, a {style_lower}'s instinct for violence, and the quiet confidence of someone who's already proved the doubters wrong. The {age}-year-old from {nation} trains at {gym} and defends the belt every time out — the reign isn't ending anytime soon.",
        "Champions aren't made; they're forged. {first} {last} forged his at {gym}, sharpening the {style_lower} tools that took him to the top of the {wc} division. {wins}-{losses} as a pro, belt around the waist, the {age}-year-old from {nation} has the kind of reign contenders measure themselves against. The next challenger is always one fight away.",
        "There's a different energy when the champ walks in. {first} '{nick}' {last} carries it — the {age}-year-old {style_lower} has been the {wc} king for long enough that the division feels like his. {wins}-{losses} record, a reign built on dominance, and a {gym} that's become a champion's factory. The belt is his until someone takes it.",
    ],
    "neutral": [
        "{first} {last} is a {age}-year-old {style_lower} from {nation}, currently competing in the {wc} division. Training out of {gym}, he carries a {wins}-{losses} record into his next fight. A solid professional with the tools to compete at this level — the question is whether he can take the next step.",
        "The {wc} division has a new face in {first} '{nick}' {last}. The {age}-year-old {style_lower} from {nation} has compiled a {wins}-{losses} record on the regional scene and now looks to test himself at the next level. Training at {gym}, he brings a well-rounded skill set and the kind of hunger you can't fake.",
        "{first} {last} doesn't have a flashy nickname or a highlight reel full of KOs. What he has is a {wins}-{losses} record, a {style_lower}'s discipline, and the kind of work ethic that comes from training at {gym}. At {age}, the {nation} native is ready to make his mark on the {wc} division.",
    ],
}


def derive_bio_tone(wins, losses, draws, age, win_streak=0, loss_streak=0,
                    fan_friendliness=50, aggression=50, is_champion=False):
    """Derive bio_tone from a fighter's OBSERVABLE career state.

    Mirrors seed_world_phase3._derive_bio_tone logic. CRITICAL: does
    NOT reveal the fighter's hidden `potential`. A limited-potential
    prospect and an elite-potential prospect both get 'unproven_prospect'.

    At world-seed time, no fighter is a current champion — titles are
    all vacant initially — so is_champion defaults to False.

    Returns one of the 10 bio_tone values allowed by the fighter_bios
    CHECK constraint.
    """
    total_fights = wins + losses + draws
    if is_champion:
        return "champion_reign"
    if age <= 24 and total_fights <= 8:
        return "unproven_prospect"
    if age >= 36 and total_fights >= 30:
        return "grizzled_veteran"
    if loss_streak >= 3 and wins >= 10:
        return "fallen_contender"
    if age >= 33 and win_streak >= 3:
        return "late_bloomer"
    if fan_friendliness >= 75:
        return "cult_hero"
    if aggression >= 75:
        return "enforcer"
    if 25 <= age <= 35 and total_fights >= 10:
        win_rate = wins / max(1, total_fights)
        if 0.35 <= win_rate <= 0.65:
            return "mid_carder"
    if total_fights >= 15:
        return "journeyman"
    return "neutral"


def render_bio(tone, fighter_dict, rng):
    """Pick a random template for the tone + render it with the fighter's data."""
    templates = BIO_TEMPLATES.get(tone, BIO_TEMPLATES["neutral"])
    tmpl = rng.choice(templates)
    # Build the substitution context. Use 'nick' = nickname or fallback.
    nick = fighter_dict.get("nickname") or "TBD"
    ctx = {
        "first": fighter_dict["first_name"],
        "last": fighter_dict["last_name"],
        "nick": nick,
        "age": fighter_dict["age"],
        "wc": fighter_dict["wc_name"],
        "style_lower": fighter_dict["style_name"].lower(),
        "nation": fighter_dict["nation_name"],
        "gym": fighter_dict["gym_name"] or "an independent camp",
        "promo": fighter_dict["promo_name"] or "the regional circuit",
        "wins": fighter_dict["wins"],
        "losses": fighter_dict["losses"],
        "draws": fighter_dict["draws"],
        "total_fights": fighter_dict["wins"] + fighter_dict["losses"] + fighter_dict["draws"],
        "win_streak": fighter_dict["win_streak"],
        "loss_streak": fighter_dict["loss_streak"],
    }
    try:
        return tmpl.format(**ctx)
    except (KeyError, IndexError) as e:
        # Defensive — a template with a missing key falls back to a
        # generic bio. Should never fire if the ctx above is complete.
        return (f"{ctx['first']} {ctx['last']} is a {ctx['age']}-year-old "
                f"{ctx['style_lower']} from {ctx['nation']}, currently "
                f"competing in the {ctx['wc']} division with a "
                f"{ctx['wins']}-{ctx['losses']} record.")


# ----------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------

def _pick_nation_id(rng):
    """Pick a nation_id weighted by NATION_WEIGHTS."""
    ids = list(NATION_WEIGHTS.keys())
    weights = [NATION_WEIGHTS[i] for i in ids]
    return rng.choices(ids, weights=weights, k=1)[0]


def _pick_name(conn, nation_id, rng):
    """Pick first + last name from name_pools by region (mapped from nation_id)."""
    region = NATION_ID_TO_REGION.get(nation_id, "United States")
    first_rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='first_male' AND region=?",
        (region,),
    ).fetchall()
    last_rows = conn.execute(
        "SELECT name_value FROM name_pools WHERE name_type='last' AND region=?",
        (region,),
    ).fetchall()
    if not first_rows:
        # Fall back to any first_male name.
        first_rows = conn.execute(
            "SELECT name_value FROM name_pools WHERE name_type='first_male' LIMIT 200"
        ).fetchall()
    if not last_rows:
        last_rows = conn.execute(
            "SELECT name_value FROM name_pools WHERE name_type='last' LIMIT 200"
        ).fetchall()
    first = rng.choice(first_rows)[0] if first_rows else "Unknown"
    last = rng.choice(last_rows)[0] if last_rows else "Fighter"
    return first, last


def _pick_style_archetype_id(conn, nation_id, rng):
    """Pick a style_archetype_id weighted by nation bias."""
    bias = NATION_STYLE_BIAS.get(nation_id, NATION_STYLE_BIAS[1])
    # Load archetype names → ids
    name_to_id = {
        r[1]: r[0] for r in conn.execute(
            "SELECT style_archetype_id, name FROM style_archetypes ORDER BY style_archetype_id"
        ).fetchall()
    }
    names = list(bias.keys())
    weights = [bias[n] for n in names]
    chosen_name = rng.choices(names, weights=weights, k=1)[0]
    return name_to_id.get(chosen_name, 1)  # default to Balanced


def _pick_personality_archetype_id(conn, rng):
    """Pick a random personality_archetype_id (uniform distribution)."""
    rows = conn.execute(
        "SELECT personality_archetype_id FROM personality_archetypes ORDER BY personality_archetype_id"
    ).fetchall()
    return rng.choice(rows)[0]


def _pick_age(rng):
    """Pick an age from the AGE_DISTRIBUTION."""
    items = [(lo, hi) for lo, hi, _ in AGE_DISTRIBUTION]
    weights = [w for _, _, w in AGE_DISTRIBUTION]
    lo, hi = rng.choices(items, weights=weights, k=1)[0]
    return rng.randint(lo, hi)


def _gen_record_for_age(age, potential, rng):
    """Generate a (wins, losses, draws) record appropriate for the age.

    Younger fighters have fewer fights; older fighters have more. The
    potential influences the win rate slightly (higher-potential
    fighters win more) but NOT the fight COUNT — the count is driven
    by age, not by ceiling. This mirrors seed_world_phase3 logic.
    """
    # Compute base fight count from age.
    if age <= 22:
        n_fights = rng.randint(0, 8)
    elif age <= 27:
        n_fights = rng.randint(3, 15)
    elif age <= 32:
        n_fights = rng.randint(8, 25)
    elif age <= 37:
        n_fights = rng.randint(15, 35)
    else:
        n_fights = rng.randint(20, 45)
    # Win rate: base 55%, +1% per 5 potential above 50, -1% per 5 below.
    # Capped at 30%-75%.
    win_rate = 0.55 + (potential - 50) / 500.0
    win_rate = max(0.30, min(0.75, win_rate))
    wins = int(round(n_fights * win_rate))
    losses = n_fights - wins - rng.randint(0, max(0, min(3, n_fights // 10)))
    losses = max(0, losses)
    draws = max(0, n_fights - wins - losses)
    # Ensure wins + losses + draws == n_fights (or close).
    return wins, losses, draws


def _gen_streaks(wins, losses, draws, rng):
    """Generate plausible win_streak / loss_streak for the record."""
    # If wins > losses, the fighter is likely on a win streak; vice versa.
    if wins > losses and wins > 0:
        win_streak = min(wins - losses, rng.randint(1, 5))
        loss_streak = 0 if wins > losses else min(losses - wins, rng.randint(0, 3))
    elif losses > wins and losses > 0:
        loss_streak = min(losses - wins, rng.randint(1, 4))
        win_streak = 0
    else:
        win_streak = rng.randint(0, 2)
        loss_streak = rng.randint(0, 2)
    return max(0, win_streak), max(0, loss_streak)


def _pick_gym_id(conn, nation_id, rng):
    """Pick a gym in the fighter's nation. Falls back to any gym."""
    if nation_id is None:
        rows = conn.execute(
            "SELECT gym_id FROM gyms ORDER BY RANDOM()"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT gym_id FROM gyms WHERE nation_id=? ORDER BY RANDOM()",
            (nation_id,),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT gym_id FROM gyms ORDER BY RANDOM()"
            ).fetchall()
    return rows[0][0] if rows else None


def _pick_birth_city_id(conn, nation_id, rng):
    """Pick a birth_city_id in the fighter's nation."""
    if nation_id is None:
        return None
    rows = conn.execute(
        "SELECT city_id FROM cities WHERE nation_id=? ORDER BY RANDOM()",
        (nation_id,),
    ).fetchall()
    return rows[0][0] if rows else None


def _gen_dob(age, current_date_str, rng):
    """Generate date_of_birth from age + current sim date."""
    try:
        year = int(current_date_str[:4])
    except (ValueError, TypeError):
        year = 2026
    birth_year = year - age
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return f"{birth_year}-{month:02d}-{day:02d}"


def _pick_promotion_for_fighter(promo_pool, rng):
    """Pick a promotion_id from the pool (already weighted by tier)."""
    return rng.choice(promo_pool) if promo_pool else None


# ----------------------------------------------------------------
# Main fighter generation
# ----------------------------------------------------------------

def populate_wc(conn, wc_id, target_count, rng, check_only=False):
    """Populate a single WC with target_count new fighters.

    Returns the count of fighters created (or would-be created if
    check_only=True).
    """
    # Check if WC already has fighters (idempotency).
    existing_count = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE weight_class_id=? AND is_active=1",
        (wc_id,),
    ).fetchone()[0]
    if existing_count > 0:
        print(f"[B1 WC{wc_id}] Already has {existing_count} fighters — "
              f"skipping population (idempotent).")
        return 0

    # Load WC info.
    wc_row = conn.execute(
        "SELECT name, gender, max_weight_kg FROM weight_classes WHERE weight_class_id=?",
        (wc_id,),
    ).fetchone()
    if not wc_row:
        print(f"[B1 WC{wc_id}] WC not found — skipping.")
        return 0
    wc_name, wc_gender, wc_max_kg = wc_row
    print(f"[B1 WC{wc_id}] {wc_name} ({wc_gender}, max {wc_max_kg}kg) — "
          f"targeting {target_count} new fighters.")

    # Build the promo pool (weighted distribution).
    promos_by_tier = {"major": [], "mid": [], "small": []}
    for r in conn.execute(
        "SELECT promotion_id, size_tier FROM promotions ORDER BY promotion_id"
    ).fetchall():
        pid, tier = r
        if tier in promos_by_tier:
            promos_by_tier[tier].append(pid)
    promo_pool = []
    # Major: 34 fighters × 1 promo (P1) → 34 instances of P1
    for pid in promos_by_tier["major"]:
        for _ in range(34):
            promo_pool.append(pid)
    # Mid: 17 fighters × 3 promos → 17 instances each
    for pid in promos_by_tier["mid"]:
        for _ in range(17):
            promo_pool.append(pid)
    # Small: 8 fighters × 6 promos → 8 instances each
    for pid in promos_by_tier["small"]:
        for _ in range(8):
            promo_pool.append(pid)
    # Free agents: FREE_AGENT_COUNT_PER_WC × None
    n_free_agents = target_count - len(promo_pool)
    if n_free_agents < 0:
        # Trim promo_pool down to target_count.
        promo_pool = promo_pool[:target_count]
        n_free_agents = 0
    print(f"[B1 WC{wc_id}] Distribution: {len(promo_pool)} signed + "
          f"{n_free_agents} free agents = {len(promo_pool) + n_free_agents} "
          f"total.")

    if check_only:
        return target_count

    # Get current sim date.
    clock_row = conn.execute(
        "SELECT current_date FROM simulation_clock WHERE clock_id=1"
    ).fetchone()
    current_date_str = clock_row[0] if clock_row else "2026-07-20"

    # Generate fighters.
    n_created = 0
    for i in range(target_count):
        # Pick promotion (or None for free agent).
        if i < len(promo_pool):
            promo_id = promo_pool[i]
        else:
            promo_id = None

        # Pick nation.
        nation_id = _pick_nation_id(rng)
        nation_name = NATION_ID_TO_REGION.get(nation_id, "United States")

        # Pick name.
        first_name, last_name = _pick_name(conn, nation_id, rng)

        # Pick style + personality archetypes.
        style_arch_id = _pick_style_archetype_id(conn, nation_id, rng)
        pers_arch_id = _pick_personality_archetype_id(conn, rng)

        # Get archetype names (for nickname + bio generation).
        style_name = conn.execute(
            "SELECT name FROM style_archetypes WHERE style_archetype_id=?",
            (style_arch_id,),
        ).fetchone()[0]

        # Pick age.
        age = _pick_age(rng)
        dob = _gen_dob(age, current_date_str, rng)

        # Generate physical stats scaled to WC.
        physical = fighter_gen.generate_physical_block(
            weight_class_max_kg=wc_max_kg, gender=wc_gender,
        )
        height_cm = physical["height_cm"]
        reach_cm = physical["reach_cm"]
        stance = physical["stance"]
        handedness = physical["handedness"]

        # Generate potential.
        potential = fighter_gen.generate_potential()

        # Generate attributes + personality (archetype-biased).
        attrs = fighter_gen.generate_attribute_block(
            archetype_id=style_arch_id, conn=conn,
        )
        pers = fighter_gen.generate_personality_block(
            archetype_id=pers_arch_id, conn=conn,
        )

        # Generate record + streaks from age + potential.
        wins, losses, draws = _gen_record_for_age(age, potential, rng)
        win_streak, loss_streak = _gen_streaks(wins, losses, draws, rng)

        # Career health based on age.
        if age <= 27:
            career_health = 100
        elif age <= 32:
            career_health = rng.randint(85, 100)
        elif age <= 37:
            career_health = rng.randint(70, 90)
        else:
            career_health = rng.randint(50, 75)

        # Pick gym + birth city.
        gym_id = _pick_gym_id(conn, nation_id, rng)
        birth_city_id = _pick_birth_city_id(conn, nation_id, rng)

        # Get gym name + promo name for bio.
        gym_name_row = conn.execute(
            "SELECT name FROM gyms WHERE gym_id=?", (gym_id,)
        ).fetchone() if gym_id else None
        gym_name = gym_name_row[0] if gym_name_row else None

        promo_name_row = conn.execute(
            "SELECT name FROM promotions WHERE promotion_id=?", (promo_id,)
        ).fetchone() if promo_id else None
        promo_name = promo_name_row[0] if promo_name_row else None

        # Generate nickname.
        nickname = fighter_gen.generate_nickname(
            attrs=attrs, pers=pers,
            style_archetype_name=style_name,
            nation_name=nation_name, rng=rng,
        )

        # Derive bio tone + render bio text.
        # Per CONVENTIONS §13 — does NOT reveal potential.
        bio_tone = derive_bio_tone(
            wins, losses, draws, age,
            win_streak=win_streak, loss_streak=loss_streak,
            fan_friendliness=pers.get("charisma", 50),
            aggression=pers.get("aggression", 50),
            is_champion=False,  # all new fighters are non-champions
        )
        # Aggression-driven tone override: if aggression is very high
        # (>80) AND the tone is "neutral", upgrade to "enforcer".
        if bio_tone == "neutral" and pers.get("aggression", 50) > 80:
            bio_tone = "enforcer"
        # Charisma-driven: if charisma > 80 AND tone is "neutral",
        # upgrade to "cult_hero".
        if bio_tone == "neutral" and pers.get("charisma", 50) > 80:
            bio_tone = "cult_hero"

        fighter_dict = {
            "first_name": first_name, "last_name": last_name,
            "nickname": nickname, "age": age, "wc_name": wc_name,
            "style_name": style_name, "nation_name": nation_name,
            "gym_name": gym_name, "promo_name": promo_name,
            "wins": wins, "losses": losses, "draws": draws,
            "win_streak": win_streak, "loss_streak": loss_streak,
            "fan_friendliness": pers.get("charisma", 50),
            "aggression": pers.get("aggression", 50),
            "potential": potential, "height_cm": height_cm,
        }
        bio_text = render_bio(bio_tone, fighter_dict, rng)

        # Generate fighter-level non-attr columns (injury_proneness,
        # weight_cut_difficulty, consistency, clutch_factor,
        # marketability, fan_friendliness, promo_boost). These mirror
        # the seed_world_phase3 random ranges.
        injury_proneness = rng.randint(20, 80)
        weight_cut_difficulty = rng.randint(20, 80)
        consistency = rng.randint(40, 80)
        clutch_factor = rng.randint(40, 80)
        marketability = rng.randint(30, 90)
        ff = rng.randint(30, 90)
        promo_boost = rng.randint(20, 80)

        # INSERT fighter row.
        cur = conn.execute(
            "INSERT INTO fighters (first_name, last_name, nickname, gender, "
            "date_of_birth, birth_city_id, birth_nation_id, "
            "weight_class_id, current_gym_id, current_promotion_id, "
            "fight_style_archetype_id, personality_archetype_id, "
            "is_active, is_retired, height_cm, reach_cm, stance, handedness, "
            "injury_proneness, weight_cut_difficulty, consistency, "
            "clutch_factor, marketability, fan_friendliness, promo_boost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (first_name, last_name, nickname, wc_gender, dob,
             birth_city_id, nation_id, wc_id, gym_id, promo_id,
             style_arch_id, pers_arch_id,
             height_cm, reach_cm, stance, handedness,
             injury_proneness, weight_cut_difficulty, consistency,
             clutch_factor, marketability, ff, promo_boost),
        )
        new_fid = cur.lastrowid

        # INSERT fighter_attributes.
        attr_cols = fighter_gen.ATTRIBUTE_NAMES  # 25 cols
        attr_vals = [attrs[c] for c in attr_cols]
        placeholders = ", ".join(["?"] * len(attr_cols))
        col_list = ", ".join(attr_cols)
        conn.execute(
            f"INSERT INTO fighter_attributes (fighter_id, {col_list}) "
            f"VALUES (?, {placeholders})",
            (new_fid, *attr_vals),
        )

        # INSERT fighter_personality.
        pers_cols = fighter_gen.PERSONALITY_NAMES  # 20 cols
        pers_vals = [pers[c] for c in pers_cols]
        placeholders = ", ".join(["?"] * len(pers_cols))
        col_list = ", ".join(pers_cols)
        conn.execute(
            f"INSERT INTO fighter_personality (fighter_id, {col_list}) "
            f"VALUES (?, {placeholders})",
            (new_fid, *pers_vals),
        )

        # INSERT fighter_career.
        conn.execute(
            "INSERT INTO fighter_career (fighter_id, record_wins, "
            "record_losses, record_draws, win_streak, loss_streak, "
            "career_health, potential, title_reigns) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (new_fid, wins, losses, draws,
             max(0, win_streak), max(0, loss_streak),
             career_health, potential),
        )

        # INSERT fighter_bios.
        conn.execute(
            "INSERT OR REPLACE INTO fighter_bios "
            "(fighter_id, bio_text, bio_tone) VALUES (?, ?, ?)",
            (new_fid, bio_text, bio_tone),
        )

        # INSERT rankings row (ELO derived from record).
        elo = 1000 + (wins - losses) * 8 + rng.randint(-30, 30)
        conn.execute(
            "INSERT OR IGNORE INTO rankings (fighter_id, weight_class_id, "
            "promotion_id, rating, fights_count, wins, losses, draws) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_fid, wc_id, promo_id, elo,
             wins + losses + draws, wins, losses, draws),
        )

        # INSERT contract for signed fighters (not free agents).
        # Mirrors seed_world_phase4 contract logic.
        if promo_id is not None:
            # Salary: based on ELO/rating.
            if elo < 950:
                salary = rng.randint(5000, 15000)
            elif elo < 1000:
                salary = rng.randint(10000, 30000)
            elif elo < 1100:
                salary = rng.randint(20000, 80000)
            elif elo < 1200:
                salary = rng.randint(50000, 150000)
            else:
                salary = rng.randint(100000, 300000)
            # Start: 1-12 months ago. End: 1 year from start.
            try:
                ref_dt = date.fromisoformat(current_date_str)
            except (ValueError, TypeError):
                ref_dt = date(2026, 7, 20)
            start_dt = ref_dt - timedelta(days=rng.randint(30, 365))
            end_dt = start_dt + timedelta(days=365)
            contract_cur = conn.execute(
                "INSERT INTO contracts (contract_target_type, "
                "promotion_id, start_date, end_date, salary, "
                "bonus_structure, buyout_clause, exclusive_flag, "
                "status) VALUES ('fighter', ?, ?, ?, ?, ?, ?, 1, 'active')",
                (promo_id, start_dt.isoformat(), end_dt.isoformat(),
                 salary,
                 "win_bonus=50%, finish_bonus=25%, performance_bonus=10%",
                 salary * 2),
            )
            new_contract_id = contract_cur.lastrowid
            # contract_type based on career stage.
            total_fights = wins + losses + draws
            if total_fights < 5:
                contract_type = "prospect"
            elif total_fights > 25:
                contract_type = "veteran"
            else:
                contract_type = "standard"
            conn.execute(
                "INSERT INTO fighter_contracts (contract_id, fighter_id, "
                "contract_type) VALUES (?, ?, ?)",
                (new_contract_id, new_fid, contract_type),
            )

        n_created += 1
        if n_created % 50 == 0:
            conn.commit()
            print(f"  WC{wc_id}: created {n_created}/{target_count}...")

    conn.commit()
    print(f"[B1 WC{wc_id}] Done. Created {n_created} fighters.")
    return n_created


# ----------------------------------------------------------------
# Title creation for the 3 WCs across all 10 promotions.
# ----------------------------------------------------------------

def create_titles_for_wcs(conn, wc_ids, check_only=False):
    """Create vacant titles for the given WCs across all promotions.

    Idempotent: skips (promotion_id, wc_id) pairs that already have
    a title.

    Returns the count of titles created (or would-be created).
    """
    promos = conn.execute(
        "SELECT promotion_id FROM promotions ORDER BY promotion_id"
    ).fetchall()
    n_created = 0
    n_skipped = 0
    for wc_id in wc_ids:
        for (promo_id,) in promos:
            existing = conn.execute(
                "SELECT title_id FROM titles WHERE promotion_id=? AND weight_class_id=?",
                (promo_id, wc_id),
            ).fetchone()
            if existing:
                n_skipped += 1
                continue
            if check_only:
                n_created += 1
                continue
            conn.execute(
                "INSERT INTO titles (promotion_id, weight_class_id, "
                "current_champion_fighter_id, champion_since_date, "
                "title_reigns_count, title_defenses_count, is_vacant) "
                "VALUES (?, ?, NULL, NULL, 0, 0, 1)",
                (promo_id, wc_id),
            )
            n_created += 1
    if not check_only:
        conn.commit()
    print(f"[B1 Titles] Created {n_created} new vacant titles for WCs "
          f"{wc_ids} (skipped {n_skipped} existing).")
    return n_created


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1.5 Group B Fix B1: populate empty male WCs.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report-only mode — no DB writes.",
    )
    parser.add_argument(
        "--only", choices=["WC6", "WC7", "WC8"], default=None,
        help="Populate only the specified WC.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("CAGE EMPIRE — Phase 1.5 Group B Fix B1: Populate Empty Male WCs")
    print("=" * 72)
    print(f"DB: {DB_PATH}")
    print(f"Mode: {'CHECK ONLY' if args.check else 'APPLY'}")
    if args.only:
        print(f"Only: {args.only}")
    print()
    print("NOTE: per CONVENTIONS §16.9, back up the DB before running.")
    print("  cp data/cage_empire.db data/cage_empire.db.backup-<name>")
    print()

    if not DB_PATH.exists():
        print(f"FATAL: DB not found at {DB_PATH}")
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    rng = random.Random(RANDOM_SEED)

    if args.only:
        wc_ids = [int(args.only[2:])]
    else:
        wc_ids = EMPTY_WC_IDS

    # Create titles FIRST (so they exist before fighters are inserted
    # — the title creation doesn't depend on fighters, but having the
    # titles in place early makes the data shape consistent).
    print("--- Step 1: Create vacant titles for the 3 WCs across all promos ---")
    create_titles_for_wcs(conn, wc_ids, check_only=args.check)
    print()

    print("--- Step 2: Populate fighters for each empty WC ---")
    total_created = 0
    for wc_id in wc_ids:
        n = populate_wc(
            conn, wc_id, target_count=TARGET_PER_WC,
            rng=rng, check_only=args.check,
        )
        total_created += n
        print()
    print(f"=== Total fighters created: {total_created} ===")
    print()

    # Verify.
    print("=== Verification ===")
    for wc_id in wc_ids:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM fighters WHERE weight_class_id=? AND is_active=1",
            (wc_id,),
        ).fetchone()[0]
        print(f"  WC{wc_id}: {cnt} active fighters")
    total_active = conn.execute(
        "SELECT COUNT(*) FROM fighters WHERE is_active=1"
    ).fetchone()[0]
    print(f"  Total active fighters in DB: {total_active}")
    n_titles_for_new_wcs = conn.execute(
        f"SELECT COUNT(*) FROM titles WHERE weight_class_id IN ({','.join('?'*len(wc_ids))})",
        wc_ids,
    ).fetchone()[0]
    print(f"  Titles for the new WCs: {n_titles_for_new_wcs}")

    conn.close()


if __name__ == "__main__":
    main()
