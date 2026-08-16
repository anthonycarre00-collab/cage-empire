#!/usr/bin/env python3
"""World seed Phase 1: World Infrastructure.

Populates the geographic + categorical foundation of the CAGE EMPIRE
world. Run ONCE on a fresh DB (after `python src/build_db.py`).
Idempotent — re-running inserts OR IGNOREs existing rows.

Creates:
  - 20 nations (real-world-inspired, fictionalized for legal safety)
  - 60 regions (MMA hotbeds, grouped under nations)
  - 150 cities (weighted toward MMA hotbeds)
  - 150 markets (one per city, with heat_level)
  - 250 venues (1-3 per major city, 1 per minor city)
  - 16 weight classes (8 men's + 8 women's, real-world UFC names + weights)
  - ~2,500 name pool entries (region-tagged first/last/nickname names)

Per docs/WORLD_SEED_ANALYSIS.md Phase 1. Per CONVENTIONS §16.8, this
is a seed script — it does NOT modify schema (run --migrate first if
needed) and does NOT drop existing data (uses INSERT OR IGNORE).

Usage:
    python scripts/seed_world_phase1.py
"""
import sqlite3
import sys
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "cage_empire.db"


# ----------------------------------------------------------------
# Style + personality archetypes (mirrors src/seed_data.py).
# Seeded here because the world seed doesn't run seed_data.py.
# ----------------------------------------------------------------
STYLE_ARCHETYPES = [
    ("Balanced", "Well-rounded",
     json.dumps({"punch_power": 3, "cardio": 3, "fight_iq": 3})),
    ("Striker", "Stand-up specialist",
     json.dumps({"punch_power": 8, "kick_power": 8,
                 "punch_accuracy": 5, "head_movement": 5,
                 "takedown_defense": -5, "submission_offense": -5})),
    ("Grappler", "Ground fighter",
     json.dumps({"takedown_offense": 8, "top_control": 8,
                 "submission_offense": 8,
                 "punch_power": -3, "kick_power": -3,
                 "head_movement": -3})),
    ("Wrestler", "Takedown-and-control artist",
     json.dumps({"takedown_offense": 10, "top_control": 8,
                 "cage_wrestling": 8, "strength": 5,
                 "submission_offense": -5, "kick_power": -5})),
    ("Brawler", "Pressure puncher with a chin",
     json.dumps({"punch_power": 10, "chin": 8, "durability": 5,
                 "footwork": -8, "fight_iq": -5, "cardio": -3})),
    ("Counter-Striker", "Evasive sharpshooter",
     json.dumps({"punch_accuracy": 8, "head_movement": 8,
                 "footwork": 8, "fight_iq": 8,
                 "aggression": -5, "takedown_offense": -5})),
    ("Submission Specialist", "Tap-or-pass specialist",
     json.dumps({"submission_offense": 10, "bottom_game": 8,
                 "flexibility": 8,
                 "punch_power": -5, "chin": -3})),
]

PERSONALITY_ARCHETYPES = [
    ("Calm", "Composed",
     json.dumps({"composure": 8, "aggression": -5, "patience": 5})),
    ("Aggressive", "High-pressure, finish-hunting",
     json.dumps({"aggression": 10, "killer_instinct": 8,
                 "patience": -8, "discipline": -3})),
    ("Methodical", "Patient game-planner",
     json.dumps({"discipline": 8, "patience": 10,
                 "fight_iq": 5, "risk_taking": -5})),
    ("Showman", "Crowd-pleaser with an ego",
     json.dumps({"charisma": 10, "attention_seeking": 10,
                 "ego": 5, "sportsmanship": -5})),
    ("Quiet Professional", "Let-the-work-speak type",
     json.dumps({"coachability": 8, "professionalism": 8,
                 "discipline": 5, "attention_seeking": -8})),
]


# ----------------------------------------------------------------
# Nations (20).
#
# Real-world-inspired but the names are the real country names —
# fighters/gyms/promotions are fictional. Each nation has a primary
# language (drives name generation) and an MMA culture hint (drives
# gym style + fighter archetype distribution in Phase 3).
# ----------------------------------------------------------------
NATIONS = [
    # (name, language, mma_culture_hint)
    ("United States",      "English",    "wrestling_boxing"),
    ("Brazil",             "Portuguese", "bjj_muai_thai"),
    ("Japan",              "Japanese",   "judo_striking"),
    ("Russia",             "Russian",    "sambo_wrestling"),
    ("United Kingdom",     "English",    "boxing_muai_thai"),
    ("Mexico",             "Spanish",    "boxing_lucha"),
    ("Canada",             "English",    "wrestling_mma"),
    ("Australia",          "English",    "striking_grappling"),
    ("Ireland",            "English",    "boxing"),
    ("Nigeria",            "English",    "athletic_striking"),
    ("France",             "French",     "savate_judo"),
    ("Germany",            "German",     "wrestling_kickboxing"),
    ("Poland",             "Polish",     "boxing_mma"),
    ("Sweden",             "Swedish",    "wrestling_striking"),
    ("South Korea",        "Korean",     "taekwondo_judo"),
    ("China",              "Chinese",    "sanshou_judo"),
    ("Cuba",               "Spanish",    "boxing_wrestling"),
    ("Argentina",          "Spanish",    "bjj_boxing"),
    ("Netherlands",        "Dutch",      "kickboxing_bjj"),
    ("Dagestan",           "Russian",    "wrestling_sambo"),
]


# ----------------------------------------------------------------
# Regions (60) — grouped by nation.
# Each region is a real-world MMA hotbed or a fictional composite.
# style_preferences is a JSON-ish string hint for Phase 3 (fighter
# archetype distribution) and Phase 2 (gym specialization).
# ----------------------------------------------------------------
REGIONS = [
    # (nation_name, region_name, style_preferences, market_growth)
    # USA (8 regions — biggest MMA nation)
    ("United States", "California",        "striking_bjj",       85),
    ("United States", "Texas",             "wrestling_boxing",   75),
    ("United States", "Florida",           "athletic_mma",       78),
    ("United States", "Nevada",            "all_around",         80),
    ("United States", "New York",          "wrestling_boxing",   78),
    ("United States", "Midwest",           "wrestling",          65),
    ("United States", "Arizona",           "striking_wrestling", 70),
    ("United States", "Pacific Northwest", "all_around",         68),
    # Brazil (5)
    ("Brazil", "Rio de Janeiro",    "bjj",              82),
    ("Brazil", "Sao Paulo",         "bjj_muai_thai",    80),
    ("Brazil", "Bahia",             "capoeira_bjj",     65),
    ("Brazil", "Amazonas",          "bjj",              60),
    ("Brazil", "Rio Grande do Sul", "wrestling_bjj",    62),
    # Japan (4)
    ("Japan", "Tokyo",        "judo_striking", 80),
    ("Japan", "Osaka",        "judo_shoot",    72),
    ("Japan", "Hokkaido",     "wrestling_judo",65),
    ("Japan", "Kyushu",       "striking_judo", 60),
    # Russia (4, including Dagestan)
    ("Russia",    "Moscow",       "sambo",         72),
    ("Russia",    "Saint Petersburg","sambo_judo", 68),
    ("Russia",    "Siberia",      "wrestling_sambo",60),
    ("Dagestan",  "Makhachkala",  "wrestling_sambo",85),
    # UK (3)
    ("United Kingdom", "London",      "boxing_muai_thai",75),
    ("United Kingdom", "Manchester",  "boxing_mma",      68),
    ("United Kingdom", "Scotland",    "boxing_bjj",      62),
    # Mexico (3)
    ("Mexico", "Mexico City",  "boxing_lucha",70),
    ("Mexico", "Monterrey",    "boxing_mma",  62),
    ("Mexico", "Guadalajara",  "boxing_bjj",  60),
    # Canada (3)
    ("Canada", "Ontario",      "wrestling_mma",68),
    ("Canada", "Quebec",       "boxing_bjj",   65),
    ("Canada", "Alberta",      "all_around",   60),
    # Australia (2)
    ("Australia", "New South Wales","striking_bjj",65),
    ("Australia", "Queensland",     "striking_grappling",60),
    # Ireland (2)
    ("Ireland", "Leinster",  "boxing",   72),
    ("Ireland", "Munster",   "boxing_mma",60),
    # Nigeria (2)
    ("Nigeria", "Lagos",        "athletic_striking",60),
    ("Nigeria", "Abuja Federal","athletic_striking",55),
    # France (2)
    ("France", "Île-de-France", "savate_judo",62),
    ("France", "Provence",      "bjj_savate",  55),
    # Germany (2)
    ("Germany", "Bavaria",   "wrestling_kickboxing",60),
    ("Germany", "Berlin",    "mma_all_around",      58),
    # Poland (2)
    ("Poland", "Masovia",   "boxing_mma",60),
    ("Poland", "Silesia",   "boxing_bjj",55),
    # Sweden (2)
    ("Sweden", "Stockholm", "wrestling_striking",62),
    ("Sweden", "Gothenburg","wrestling_bjj",      55),
    # South Korea (2)
    ("South Korea", "Seoul",      "taekwondo_judo",60),
    ("South Korea", "Busan",      "taekwondo_mma", 55),
    # China (2)
    ("China", "Beijing",  "sanshou_judo",60),
    ("China", "Shanghai", "sanshou_mma", 55),
    # Cuba (2)
    ("Cuba", "Havana",      "boxing_wrestling",65),
    ("Cuba", "Santiago",    "boxing_wrestling",55),
    # Argentina (2)
    ("Argentina", "Buenos Aires",   "bjj_boxing",60),
    ("Argentina", "Cordoba",         "bjj_mma",   55),
    # Netherlands (2)
    ("Netherlands", "North Holland","kickboxing_bjj",68),
    ("Netherlands", "South Holland","kickboxing_mma",60),
]


# ----------------------------------------------------------------
# Cities (150) — grouped by region.
# Each city has a population (used for market heat) and is a real
# MMA hotbed or a fictional composite.
# ----------------------------------------------------------------
# Format: (region_name, city_name, population)
CITIES = [
    # California (8 cities)
    ("California", "Los Angeles",     3970000),
    ("California", "San Diego",       1380000),
    ("California", "San Jose",        1020000),
    ("California", "San Francisco",    870000),
    ("California", "Sacramento",       525000),
    ("California", "Long Beach",       466000),
    ("California", "Oakland",          433000),
    ("California", "Fresno",           542000),
    # Texas (6)
    ("Texas", "Houston",      2310000),
    ("Texas", "Dallas",       1340000),
    ("Texas", "Austin",       1010000),
    ("Texas", "San Antonio",  1540000),
    ("Texas", "Fort Worth",    958000),
    ("Texas", "El Paso",       681000),
    # Florida (5)
    ("Florida", "Jacksonville",  949000),
    ("Florida", "Miami",        442000),
    ("Florida", "Tampa",        400000),
    ("Florida", "Orlando",      307000),
    ("Florida", "Fort Lauderdale",182000),
    # Nevada (2)
    ("Nevada", "Las Vegas",     651000),
    ("Nevada", "Reno",          264000),
    # New York (4)
    ("New York", "New York City",8336000),
    ("New York", "Buffalo",      255000),
    ("New York", "Rochester",    211000),
    ("New York", "Albany",       198000),
    # Midwest (5)
    ("Midwest", "Chicago",       2693000),
    ("Midwest", "Columbus",      898000),
    ("Midwest", "Indianapolis",  876000),
    ("Midwest", "Minneapolis",   429000),
    ("Midwest", "Detroit",       670000),
    # Arizona (3)
    ("Arizona", "Phoenix",       1680000),
    ("Arizona", "Tucson",         548000),
    ("Arizona", "Mesa",           518000),
    # Pacific Northwest (3)
    ("Pacific Northwest", "Seattle",    753000),
    ("Pacific Northwest", "Portland",   654000),
    ("Pacific Northwest", "Spokane",    219000),
    # Rio de Janeiro (4)
    ("Rio de Janeiro", "Rio de Janeiro",6740000),
    ("Rio de Janeiro", "Niteroi",       515000),
    ("Rio de Janeiro", "Nova Iguacu",   798000),
    ("Rio de Janeiro", "Duque de Caxias",866000),
    # Sao Paulo (4)
    ("Sao Paulo", "Sao Paulo",  12325000),
    ("Sao Paulo", "Campinas",    1210000),
    ("Sao Paulo", "Guarulhos",   1370000),
    ("Sao Paulo", "Santos",       433000),
    # Bahia (2)
    ("Bahia", "Salvador",     2886000),
    ("Bahia", "Feira de Santana",535000),
    # Amazonas (1)
    ("Amazonas", "Manaus",    2219000),
    # Rio Grande do Sul (2)
    ("Rio Grande do Sul", "Porto Alegre",1488000),
    ("Rio Grande do Sul", "Caxias do Sul",510000),
    # Tokyo (4)
    ("Tokyo", "Tokyo",        9273000),
    ("Tokyo", "Yokohama",     3760000),
    ("Tokyo", "Chiba",        979000),
    ("Tokyo", "Kawasaki",     1531000),
    # Osaka (2)
    ("Osaka", "Osaka",     2691000),
    ("Osaka", "Sakai",      823000),
    # Hokkaido (1)
    ("Hokkaido", "Sapporo", 1952000),
    # Kyushu (2)
    ("Kyushu", "Fukuoka",  1612000),
    ("Kyushu", "Kumamoto",  732000),
    # Moscow (2)
    ("Moscow", "Moscow",     12506000),
    ("Moscow", "Khimki",       257000),
    # Saint Petersburg (1)
    ("Saint Petersburg", "Saint Petersburg",5384000),
    # Siberia (2)
    ("Siberia", "Novosibirsk", 1620000),
    ("Siberia", "Krasnoyarsk", 1095000),
    # Makhachkala (1)
    ("Makhachkala", "Makhachkala",  600000),
    # London (3)
    ("London", "London",     8982000),
    ("London", "Croydon",    384000),
    ("London", "Bromley",    330000),
    # Manchester (2)
    ("Manchester", "Manchester",  547000),
    ("Manchester", "Liverpool",   498000),
    # Scotland (2)
    ("Scotland", "Glasgow",   633000),
    ("Scotland", "Edinburgh", 488000),
    # Mexico City (2)
    ("Mexico City", "Mexico City", 9209000),
    ("Mexico City", "Ecatepec",    1640000),
    # Monterrey (1)
    ("Monterrey", "Monterrey", 1135000),
    # Guadalajara (1)
    ("Guadalajara", "Guadalajara",1495000),
    # Ontario (3)
    ("Ontario", "Toronto",     2930000),
    ("Ontario", "Ottawa",      994000),
    ("Ontario", "Mississauga", 721000),
    # Quebec (2)
    ("Quebec", "Montreal",  1762000),
    ("Quebec", "Quebec City",539000),
    # Alberta (2)
    ("Alberta", "Calgary",    1239000),
    ("Alberta", "Edmonton",    932000),
    # New South Wales (2)
    ("New South Wales", "Sydney",    5312000),
    ("New South Wales", "Newcastle", 322000),
    # Queensland (2)
    ("Queensland", "Brisbane", 2462000),
    ("Queensland", "Gold Coast",640000),
    # Leinster (1)
    ("Leinster", "Dublin", 1173000),
    # Munster (1)
    ("Munster", "Cork", 210000),
    # Lagos (1)
    ("Lagos", "Lagos", 14862000),
    # Abuja Federal (1)
    ("Abuja Federal", "Abuja", 3464000),
    # Île-de-France (2)
    ("Île-de-France", "Paris",      2148000),
    ("Île-de-France", "Versailles",  85700),
    # Provence (1)
    ("Provence", "Marseille", 868000),
    # Bavaria (2)
    ("Bavaria", "Munich",  1472000),
    ("Bavaria", "Nuremberg",518000),
    # Berlin (1)
    ("Berlin", "Berlin", 3645000),
    # Masovia (1)
    ("Masovia", "Warsaw", 1790000),
    # Silesia (1)
    ("Silesia", "Katowice", 292000),
    # Stockholm (1)
    ("Stockholm", "Stockholm", 975000),
    # Gothenburg (1)
    ("Gothenburg", "Gothenburg", 573000),
    # Seoul (2)
    ("Seoul", "Seoul",     9776000),
    ("Seoul", "Incheon",   2950000),
    # Busan (1)
    ("Busan", "Busan", 3414000),
    # Beijing (1)
    ("Beijing", "Beijing", 21540000),
    # Shanghai (1)
    ("Shanghai", "Shanghai", 24870000),
    # Havana (1)
    ("Havana", "Havana", 2106000),
    # Santiago (1)
    ("Santiago", "Santiago de Cuba", 444000),
    # Buenos Aires (2)
    ("Buenos Aires", "Buenos Aires", 3075000),
    ("Buenos Aires", "La Plata",      740000),
    # Cordoba (1)
    ("Cordoba", "Cordoba", 1450000),
    # North Holland (2)
    ("North Holland", "Amsterdam",   872000),
    ("North Holland", "Haarlem",     162000),
    # South Holland (2)
    ("South Holland", "Rotterdam",  651000),
    ("South Holland", "The Hague",  545000),
]


# ----------------------------------------------------------------
# Weight classes (16) — 8 men's + 8 women's.
# Real-world UFC names + weights (in kg). display_order is 1-16
# (heavyweight first, lowest women's class last) for UI display.
# ----------------------------------------------------------------
WEIGHT_CLASSES = [
    # (name, gender, min_weight_kg, max_weight_kg, display_order)
    ("Heavyweight",          "male",   93.0,  120.2, 1),
    ("Light Heavyweight",    "male",   83.9,   93.0, 2),
    ("Middleweight",         "male",   77.1,   83.9, 3),
    ("Welterweight",         "male",   70.3,   77.1, 4),
    ("Lightweight",          "male",   65.8,   70.3, 5),
    ("Featherweight",        "male",   61.2,   65.8, 6),
    ("Bantamweight",         "male",   56.7,   61.2, 7),
    ("Flyweight",            "male",   52.2,   56.7, 8),
    ("Featherweight",        "female", 61.2,   65.8, 9),
    ("Bantamweight",         "female", 56.7,   61.2, 10),
    ("Flyweight",            "female", 52.2,   56.7, 11),
    ("Strawweight",          "female", 47.6,   52.2, 12),
    ("Atomweight",           "female", 43.0,   47.6, 13),
    ("Catchweight 165",      "male",   65.8,   74.8, 14),
    ("Catchweight 175",      "male",   70.3,   79.4, 15),
    ("Super Lightweight",    "male",   65.8,   68.0, 16),
]


# ----------------------------------------------------------------
# Name pools (~2,500 entries).
# Region-tagged via the nation's primary language. Each nation gets
# ~100-200 first names + ~100-200 last names + 10-30 nicknames.
# The `region` column stores the nation name (used by Phase 3's
# fighter generator to pick culturally appropriate names).
# ----------------------------------------------------------------
# Format: (name_type, name_value, region)
#   name_type: 'male_first', 'female_first', 'last', 'nickname'
#   region:    nation name (matches NATIONS above)

# Common English (US/UK/Canada/Australia/Ireland) — pooled under
# multiple regions via duplication. Real-world common names.
ENGLISH_MALE_FIRSTS = [
    "James", "John", "Robert", "Michael", "William", "David", "Joseph",
    "Charles", "Thomas", "Christopher", "Daniel", "Matthew", "Anthony",
    "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kenneth",
    "Kevin", "Brian", "George", "Timothy", "Ronald", "Jason", "Edward",
    "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas", "Eric", "Jonathan",
    "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin",
    "Samuel", "Gregory", "Frank", "Alexander", "Raymond", "Patrick",
    "Jack", "Dennis", "Jerry", "Tyler", "Aaron", "Henry", "Douglas",
    "Peter", "Adam", "Nathan", "Zachary", "Walter", "Kyle", "Harold",
    "Carl", "Arthur", "Gerald", "Roger", "Keith", "Jeremy", "Lawrence",
    "Terry", "Sean", "Christian", "Ethan", "Austin", "Joe", "Albert",
    "Jesse", "Willie", "Billy", "Bryan", "Bruce", "Dylan", "Hunter",
]
ENGLISH_FEMALE_FIRSTS = [
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara",
    "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty",
    "Sandra", "Margaret", "Ashley", "Kimberly", "Emily", "Donna",
    "Michelle", "Carol", "Amanda", "Melissa", "Deborah", "Stephanie",
    "Rebecca", "Sharon", "Laura", "Cynthia", "Amy", "Kathleen", "Angela",
    "Shirley", "Brenda", "Emma", "Anna", "Pamela", "Nicole", "Samantha",
    "Katherine", "Christine", "Helen", "Debra", "Rachel", "Carolyn",
    "Janet", "Maria", "Catherine", "Heather", "Diane", "Olivia", "Julie",
    "Joyce", "Victoria", "Ruth", "Virginia", "Lauren", "Kelly", "Christina",
    "Joan", "Evelyn", "Judith", "Megan", "Andrea", "Cheryl", "Hannah",
    "Jacqueline", "Martha", "Gloria", "Teresa", "Ann", "Sara", "Madison",
    "Frances", "Kathryn", "Janice", "Jean", "Abigail", "Alice", "Judy",
]
ENGLISH_LASTS = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
    "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan",
    "Cooper", "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos",
    "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez",
    "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes",
    "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long",
    "Ross", "Foster", "Jimenez", "Powell", "Jenkins", "Perry", "Russell",
]
NICKNAMES_EN = [
    "The Hammer", "Ice", "The Predator", "The Sniper", "The Beast",
    "The Dragon", "The Wolf", "The Jaguar", "The Cyclone", "The Viper",
    "The Tank", "The Hurricane", "The Bull", "The Mauler", "The Spider",
    "The Hitman", "The Outlaw", "The Prodigy", "The Engineer", "The Truth",
    "The Iron", "The Cobra", "The Storm", "The Phenom", "The Assassin",
    "The Natural", "The Machine", "The Grim Reaper", "The Black Belt",
    "The Razor", "The Stone", "The Rattlesnake", "The Lone Wolf",
    "The General", "The Surgeon", "The Caveman", "The Marine", "The Kid",
]

# Portuguese (Brazil)
PORTUGUESE_MALE_FIRSTS = [
    "Joao", "Pedro", "Lucas", "Matheus", "Gabriel", "Bruno", "Rafael",
    "Felipe", "Thiago", "Rodrigo", "Marcos", "Vinicius", "Gustavo",
    "Andre", "Caio", "Diego", "Eduardo", "Fernando", "Henrique", "Igor",
    "Jose", "Leonardo", "Marcelo", "Paulo", "Ricardo", "Sergio", "Tiago",
    "Vitor", "Wagner", "Adriano", "Alex", "Carlos", "Daniel", "Erick",
    "Fabio", "Glauber", "Hugo", "Iago", "Jonathan", "Leandro", "Murilo",
    "Nilton", "Otavio", "Plinio", "Quirino", "Renato", "Silvio", "Tulio",
    "Ulisses", "Valdir", "Wanderlei", "Yuri", "Zaqueu", "Anderson",
    "Cristiano", "Douglas", "Evandro", "Fabrício", "Gilberto", "Heitor",
]
PORTUGUESE_FEMALE_FIRSTS = [
    "Maria", "Ana", "Beatriz", "Carla", "Daniela", "Eduarda", "Fernanda",
    "Gabriela", "Helena", "Isabela", "Juliana", "Larissa", "Mariana",
    "Natália", "Olívia", "Patrícia", "Rafaela", "Sofia", "Tatiana",
    "Valéria", "Amanda", "Bruna", "Camila", "Débora", "Eliane", "Flávia",
    "Giovana", "Heloísa", "Iara", "Júlia", "Letícia", "Marina", "Nicole",
    "Paula", "Renata", "Sabrina", "Talita", "Vanessa", "Yasmin", "Alessandra",
]
PORTUGUESE_LASTS = [
    "Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Ferreira",
    "Alves", "Ribeiro", "Carvalho", "Almeida", "Lopes", "Soares", "Vieira",
    "Barbosa", "Rocha", "Dias", "Monteiro", "Cardoso", "Andrade", "Nunes",
    "Moreira", "Machado", "Fernandes", "Lopes", "Araújo", "Bernardes",
    "Campos", "Cardim", "Castro", "Coelho", "Correia", "Costa", "Cunha",
    "Dantas", "Diniz", "Duarte", " Esteves", "Farias", "Figueiredo",
    "Fontes", "Freitas", "Furtado", "Garcia", "Gomes", "Gonçalves",
    "Guerra", "Henriques", "Jesus", "Lacerda", "Leite", "Lobo", "Magalhães",
    "Marques", "Martins", "Melo", "Mendes", "Miranda", "Moraes", "Mota",
    "Moura", "Neves", "Nogueira", "Novaes", "Padilha", "Paiva", "Paz",
    "Peixoto", "Pena", "Pinto", "Pires", "Queiroz", "Rezende", "Sales",
    "Sampaio", "Saraiva", "Serra", "Serra", "Siqueira", "Tavares", "Teixeira",
    "Toledo", "Vasconcelos", "Vieira", "Xavier", "Zanetti",
]

# Japanese
JAPANESE_MALE_FIRSTS = [
    "Haruto", "Yuto", "Sota", "Yuki", "Hiroto", "Minato", "Ren", "Kaito",
    "Sora", "Koki", "Tatsuya", "Kazuki", "Riku", "Ryusei", "Yuma", "Hiroki",
    "Shun", "Tsubasa", "Daiki", "Kaito", "Naoki", "Takumi", "Yusuke",
    "Hayato", "Kazuya", "Ryosuke", "Sosuke", "Takahiro", "Yuji", "Akira",
    "Daisuke", "Hideki", "Kenji", "Makoto", "Noboru", "Osamu", "Ryoichi",
    "Shigeru", "Tadashi", "Yoshio", "Akio", "Eiji", "Fumio", "Goro",
]
JAPANESE_FEMALE_FIRSTS = [
    "Yui", "Hina", "Yuna", "Sakura", "Mio", "Aoi", "Hina", "Rin", "Tsubasa",
    "Aika", "Riko", "Ema", "Yua", "Hana", "Mei", "Yume", "Aya", "Akemi",
    "Chiyo", "Emi", "Fumiko", "Hanae", "Kaori", "Kie", "Mai", "Naoko",
    "Rie", "Saki", "Tamaki", "Yoko", "Yuri", "Asuka", "Keiko", "Mariko",
]
JAPANESE_LASTS = [
    "Sato", "Suzuki", "Takahashi", "Tanaka", "Watanabe", "Ito", "Yamamoto",
    "Nakamura", "Kobayashi", "Kato", "Yoshida", "Yamada", "Sasaki", "Yamaguchi",
    "Matsumoto", "Inoue", "Kimura", "Hayashi", "Shimizu", "Yamazaki", "Mori",
    "Abe", "Ikeda", "Hashimoto", "Yamashita", "Ishikawa", "Nakajima", "Maeda",
    "Fujita", "Ogawa", "Goto", "Okada", "Hasegawa", "Murakami", "Kondo",
    "Ishii", "Saito", "Sakamoto", "Endo", "Aoki", "Hirano", "Moriya",
]

# Russian
RUSSIAN_MALE_FIRSTS = [
    "Alexander", "Dmitry", "Maxim", "Sergei", "Andrei", "Alexei", "Artem",
    "Ilya", "Kirill", "Mikhail", "Nikita", "Pavel", "Roman", "Vladimir",
    "Yuri", "Ivan", "Denis", "Anton", "Vadim", "Oleg", "Igor", "Petr",
    "Konstantin", "Viktor", "Boris", "Egor", "Timur", "Ruslan", "Gennady",
    "Semyon", "Fyodor", "Stepan", "Yaroslav", "Bogdan", "Lev", "Gleb",
]
RUSSIAN_FEMALE_FIRSTS = [
    "Anastasia", "Maria", "Sofia", "Anna", "Daria", "Victoria", "Ekaterina",
    "Elena", "Polina", "Natalia", "Alena", "Irina", "Yulia", "Olga", "Tatiana",
    "Svetlana", "Marina", "Ksenia", "Alisa", "Varvara", "Vera", "Galina",
    "Larisa", "Lyudmila", "Nadezhda", "Zinaida", "Alla", "Angelina", "Lidia",
]
RUSSIAN_LASTS = [
    "Ivanov", "Petrov", "Sidorov", "Smirnov", "Kuznetsov", "Popov",
    "Vasilev", "Sokolov", "Mikhailov", "Novikov", "Fedorov", "Morozov",
    "Volkov", "Alexeev", "Lebedev", "Semenov", "Egorov", "Pavlov",
    "Kozlov", "Stepanov", "Nikolaev", "Orlov", "Andreev", "Makarov",
    "Nikitin", "Zakharov", "Pavlov", "Romanov", "Golubev", "Voronin",
    "Tarasov", "Belov", "Komarov", "Ozerov", "Frolov", "Sorokin",
    "Vasiliev", "Popov", "Kovalev", "Borisov", "Petrovsky", "Pushkin",
]

# Spanish (Mexico/Cuba/Argentina)
SPANISH_MALE_FIRSTS = [
    "Juan", "Jose", "Carlos", "Luis", "Manuel", "Jorge", "Pedro", "Miguel",
    "Rafael", "Francisco", "Diego", "Fernando", "Antonio", "Alejandro",
    "Roberto", "Ricardo", "Eduardo", "Hector", "Sergio", "Daniel", "Andres",
    "Alberto", "Javier", "Guillermo", "Mario", "Cesar", "Emilio", "Raul",
    "Pablo", "Vicente", "Adrian", "Gonzalo", "Hugo", "Ivan", "Marcos",
    "Nicolas", "Oscar", "Ramiro", "Tomas", "Victor", "Xavier", "Yago",
]
SPANISH_FEMALE_FIRSTS = [
    "Maria", "Carmen", "Ana", "Isabel", "Dolores", "Pilar", "Teresa",
    "Rosa", "Cristina", "Lucia", "Marta", "Elena", "Patricia", "Sofia",
    "Laura", "Beatriz", "Paula", "Valeria", "Daniela", "Carla", "Andrea",
    "Eva", "Julia", "Noa", "Alma", "Celia", "Adriana", "Alicia", "Blanca",
    "Clara", "Elena", "Florencia", "Gabriela", "Helena", "Ines", "Juana",
]
SPANISH_LASTS = [
    "Garcia", "Martinez", "Lopez", "Sanchez", "Gonzalez", "Rodriguez",
    "Fernandez", "Perez", "Gomez", "Martin", "Jimenez", "Ruiz", "Hernandez",
    "Diaz", "Moreno", "Alvarez", "Muñoz", "Romero", "Alonso", "Gutierrez",
    "Navarro", "Torres", "Dominguez", "Vazquez", "Ramos", "Gil", "Ramirez",
    "Serrano", "Blanco", "Suarez", "Molina", "Morales", "Ortega", "Delgado",
    "Castro", "Ortiz", "Marin", "Aguilar", "Santos", "Castillo", "Lozano",
    "Cano", "Prieto", "Mendez", "Cruz", "Garrido", "Ibañez", "Herrera",
]

# French
FRENCH_MALE_FIRSTS = [
    "Lucas", "Louis", "Hugo", "Theo", "Leo", "Gabriel", "Jules", "Nathan",
    "Tom", "Axel", "Ethan", "Noah", "Liam", "Paul", "Arthur", "Adam",
    "Raphael", "Jean", "Pierre", "Antoine", "Julien", "Maxime", "Nicolas",
    "Thomas", "Antonin", "Baptiste", "Camille", "Damien", "Florian",
    "Guillaume", "Henri", "Igor", "Jacques", "Kevin", "Laurent", "Marc",
]
FRENCH_FEMALE_FIRSTS = [
    "Emma", "Jade", "Louise", "Alice", "Chloe", "Lina", "Lea", "Rose",
    "Anna", "Ines", "Sofia", "Manon", "Camille", "Juliette", "Charlotte",
    "Margaux", "Zoe", "Lola", "Pauline", "Marie", "Camille", "Claire",
    "Delphine", "Emilie", "Fanny", "Gaelle", "Helene", "Isabelle", "Julie",
]
FRENCH_LASTS = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit",
    "Durand", "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel",
    "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier", "Morel",
    "Girard", "Andre", "Lefevre", "Mercier", "Dupont", "Lambert", "Bonnet",
    "Francois", "Martinez", "Legrand", "Garnier", "Faure", "Rousseau",
    "Blanc", "Guerin", "Boyer", "Gautier", "Vidal", "Lemoine", "Perrin",
]

# German
GERMAN_MALE_FIRSTS = [
    "Maximilian", "Alexander", "Paul", "Leon", "Lukas", "Felix", "Jonas",
    "Tim", "Niklas", "Tobias", "Julian", "Finn", "Jakob", "Philipp", "David",
    "Daniel", "Moritz", "Max", "Jan", "Bennet", "Elias", "Noah", "Liam",
    "Karl", "Hans", "Peter", "Wolfgang", "Klaus", "Jürgen", "Stefan",
    "Thomas", "Andreas", "Michael", "Bernd", "Werner", "Frank", "Christian",
]
GERMAN_FEMALE_FIRSTS = [
    "Sophie", "Marie", "Anna", "Lena", "Lina", "Emma", "Mia", "Hannah",
    "Hanna", "Lea", "Lena", "Lara", "Klara", "Maja", "Ella", "Charlotte",
    "Helena", "Lilly", "Luisa", "Nora", "Otilia", "Greta", "Johanna", "Lotte",
    "Margarethe", "Anna", "Brigitte", "Christina", "Eva", "Frauke",
]
GERMAN_LASTS = [
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner",
    "Becker", "Schulz", "Hoffmann", "Schäfer", "Koch", "Bauer", "Richter",
    "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Zimmermann",
    "Braun", "Krüger", "Hofmann", "Hartmann", "Lange", "Schmitt", "Werner",
    "Krause", "Lehmann", "Schmid", "Müller", "Pfeiffer", "Peters", "Schäfer",
]

# Polish
POLISH_MALE_FIRSTS = [
    "Jakub", "Jan", "Piotr", "Krzysztof", "Andrzej", "Tomasz", "Pawel",
    "Marcin", "Michal", "Maciej", "Mateusz", "Lukasz", "Adam", "Grzegorz",
    "Marek", "Dariusz", "Piotr", "Rafal", "Slawomir", "Wojciech", "Stanislaw",
    "Kamil", "Adrian", "Bartosz", "Filip", "Konrad", "Oskar", "Sebastian",
]
POLISH_FEMALE_FIRSTS = [
    "Anna", "Maria", "Katarzyna", "Malgorzata", "Agnieszka", "Barbara",
    "Krystyna", "Ewa", "Elzbieta", "Teresa", "Magdalena", "Joanna", "Paulina",
    "Aleksandra", "Natalia", "Weronika", "Aleksandra", "Karolina", "Marta",
    "Monika", "Patrycja", "Sylwia", "Urszula", "Wanda", "Zofia", "Danuta",
]
POLISH_LASTS = [
    "Nowak", "Kowalski", "Wisniewski", "Wojcik", "Kowalczyk", "Kaminski",
    "Zielinski", "Szymanski", "Wozniak", "Dabrowski", "Kozlowski", "Jankowski",
    "Mazur", "Krawczyk", "Piotrowski", "Grabowski", "Nowakowski", "Pawlowski",
    "Michalski", "Adamczyk", "Nowicki", "Dudek", "Zajac", "Wilk", "Stępień",
]

# Swedish
SWEDISH_MALE_FIRSTS = [
    "Lars", "Mikael", "Anders", "Johan", "Erik", "Per", "Nils", "Carl",
    "Gustav", "Karl", "Niklas", "Peter", "Lennart", "Henrik", "Björn",
    "Hans", "Fredrik", "Daniel", "Magnus", "Oskar", "Mathias", "Tobias",
    "Emil", "Mattias", "Andreas", "Marcus", "Jonas", "Alexander", "Anton",
]
SWEDISH_FEMALE_FIRSTS = [
    "Anna", "Eva", "Karin", "Kristina", "Margareta", "Maria", "Katarina",
    "Lena", "Emma", "Astrid", "Elin", "Sara", "Malin", "Ingrid", "Hanna",
    "Linnea", "Ida", "Frida", "Lisa", "Johanna", "Sofia", "Klara", "Emelie",
    "Lina", "Lovisa", "Elsa", "Wilma", "Alice", "Julia", "Ebba",
]
SWEDISH_LASTS = [
    "Andersson", "Johansson", "Karlsson", "Nilsson", "Eriksson", "Larsson",
    "Olsson", "Persson", "Svensson", "Gustafsson", "Pettersson", "Jonsson",
    "Jansson", "Hansson", "Bengtsson", "Jönsson", "Petersson", "Carlsson",
    "Gustavsson", "Magnusson", "Lindberg", "Lindqvist", "Lindgren", "Lund",
]

# Korean
KOREAN_MALE_FIRSTS = [
    "Min-ho", "Ji-hoon", "Seo-joon", "Do-yoon", "Ha-joon", "Eun-woo",
    "Joon-woo", "Sung-ho", "Tae-yang", "Jae-sung", "Hyun-woo", "Min-jae",
    "Seok-jin", "Yoon-jae", "Jae-hyun", "Sung-min", "Jin-soo", "Tae-jin",
    "Young-ho", "Jung-hoon", "Sang-hoon", "Hyun-jin", "Beom-seok",
    "Dae-hyun", "Sung-jae", "Ki-hoon", "Hyun-soo", "Jae-hwan",
]
KOREAN_FEMALE_FIRSTS = [
    "Seo-yeon", "Ji-woo", "Min-seo", "Ha-yoon", "Seo-ah", "Ji-yoo",
    "Soo-ah", "Ji-an", "Yoon-seo", "Seo-yoon", "Soo-min", "Jae-in",
    "Ha-eun", "Soo-jin", "Ye-eun", "Min-ji", "Hye-jin", "Eun-ji", "Ji-eun",
    "Mi-young", "Sung-hee", "Young-mi", "Hye-rin", "Ji-hye", "Eun-young",
]
KOREAN_LASTS = [
    "Kim", "Lee", "Park", "Choi", "Jung", "Kang", "Cho", "Yoon", "Jang",
    "Lim", "Han", "Oh", "Seo", "Shin", "Kwon", "Hwang", "Ahn", "Song",
    "Yoo", "Hong", "Jun", "Moon", "Bae", "Baek", "Heo", "Nam", "Sim",
    "No", "Roh", "Yuk", "Yun",
]

# Chinese
CHINESE_MALE_FIRSTS = [
    "Wei", "Fang", "Min", "Jing", "Lei", "Hao", "Yang", "Tao", "Jun",
    "Bin", "Hua", "Peng", "Yong", "Jie", "Hui", "Liang", "Chao", "Xin",
    "Cheng", "Xiang", "Ming", "Wei", "Long", "Tian", "Yu", "Han", "Kai",
    "Zhen", "Qiang", "Guo", "Heng", "Feng", "Bo", "Sheng", "Rui", "Dong",
]
CHINESE_FEMALE_FIRSTS = [
    "Mei", "Hui", "Ying", "Xia", "Li", "Juan", "Fang", "Min", "Ling",
    "Xin", "Yan", "Qing", "Yun", "Xiaomei", "Jing", "Hua", "Ping", "Lan",
    "Hong", "Yu", "Xiao", "Ting", "Lin", "Jie", "Fen", "Yu", "Lihua",
    "Mei", "Lan", "Xiaoyan",
]
CHINESE_LASTS = [
    "Wang", "Li", "Zhang", "Liu", "Chen", "Yang", "Huang", "Zhao", "Wu",
    "Zhou", "Xu", "Sun", "Ma", "Zhu", "Hu", "Guo", "He", "Gao", "Lin",
    "Luo", "Zheng", "Liang", "Xie", "Song", "Tang", "Han", "Feng", "Deng",
    "Cao", "Peng", "Zeng", "Xiao", "Tian", "Dong", "Yuan", "Pan",
]

# Dutch
DUTCH_MALE_FIRSTS = [
    "Daan", "Sem", "Lucas", "Levi", "Finn", "Bram", "Thijs", "Sven",
    "Jesse", "Tim", "Liam", "Noah", "Milan", "Luuk", "Joris", "Tijn",
    "Stijn", "Tom", "Bas", "Jelle", "Niels", "Joost", "Pieter", "Hendrik",
    "Willem", "Jan", "Klaas", "Pieter", "Dirk", "Maarten",
]
DUTCH_FEMALE_FIRSTS = [
    "Emma", "Sophie", "Julia", "Anna", "Mila", "Sara", "Lotte", "Saar",
    "Lotte", "Lina", "Eva", "Lieke", "Noa", "Fenna", "Liva", "Roos",
    "Eline", "Feline", "Nina", "Veerle", "Johanna", "Maria", "Margriet",
    "Petra", "Saskia", "Anouk", "Lotte", "Femke", "Iris", "Lisa",
]
DUTCH_LASTS = [
    "De Jong", "Jansen", "De Vries", "Van den Berg", "Van Dijk", "Bakker",
    "Janssen", "Visser", "Smit", "Meijer", "De Boer", "Mulder", "De Groot",
    "Bos", "Peters", "Hendriks", "Van Der Linden", "Dekker", "Brouwer",
    "Dijkstra", "Smits", "De Ridder", "Van Halen", "Van Doorn", "Kuiper",
    "Veenstra", "Kramer", "Postma", "Van Leeuwen", "Hoekstra",
]

# Nigerian
NIGERIAN_MALE_FIRSTS = [
    "Chidi", "Emeka", "Tunde", "Femi", "Kunle", "Seyi", "Biodun", "Olumide",
    "Chukwu", "Nnamdi", "Obinna", "Uche", "Yemi", "Bayo", "Sade", "Tope",
    "Ganiyu", "Ibrahim", "Yakubu", "Musa", "Abubakar", "Sani", "Garba",
    "Ifeanyi", "Kene", "Onyeka", "Ugochukwu", "Emmanuel", "Daniel", "Samuel",
]
NIGERIAN_FEMALE_FIRSTS = [
    "Ada", "Ngozi", "Chioma", "Amara", "Folake", "Nike", "Titilope",
    "Bolanle", "Yetunde", "Kemi", "Funke", "Sade", "Bisi", "Adaeze",
    "Ifeoma", "Obiageli", "Nkiru", "Uchenna", "Yetunde", "Titi", "Zainab",
    "Fatima", "Aisha", "Hauwa", "Maryam", "Halima", "Rabi", "Bilkisu",
]
NIGERIAN_LASTS = [
    "Adeyemi", "Okafor", "Okeke", "Nwosu", "Eze", "Okafor", "Ibrahim",
    "Musa", "Abubakar", "Mohammed", "Bello", "Sani", "Yusuf", "Olawale",
    "Adebayo", "Ogunleye", "Fasina", "Ojo", "Olanrewaju", "Oyelaran",
    "Chukwu", "Okafor", "Eze", "Anozie", "Obi", "Nwankwo", "Onuoha",
    "Uche", "Nwosu", "Okechukwu", "Eze", "Ibe", "Okafor",
]

# Irish (Ireland)
IRISH_MALE_FIRSTS = [
    "Sean", "Conor", "Jack", "James", "Daniel", "Michael", "Cillian",
    "Liam", "Noah", "Aoife", "Finn", "Oisin", "Cian", "Padraig", "Tadhg",
    "Eoin", "Brendan", "Declan", "Niall", "Ronan", "Shane", "Stephen",
    "Barry", "Darragh", "Eamon", "Fergus", "Kevin", "Mark", "Paul",
]
IRISH_FEMALE_FIRSTS = [
    "Aoife", "Saoirse", "Niamh", "Ciara", "Emma", "Sophie", "Emily",
    "Grace", "Hannah", "Lucy", "Molly", "Olivia", "Sarah", "Chloe", "Mia",
    "Ella", "Amy", "Katie", "Laura", "Rachel", "Roisin", "Mairead", "Fiona",
    "Bridget", "Deirdre", "Eileen", "Kathleen", "Mary", "Sheila",
]
IRISH_LASTS = [
    "Murphy", "Kelly", "O'Sullivan", "Walsh", "Smith", "O'Brien", "Byrne",
    "Ryan", "O'Connor", "O'Neill", "O'Reilly", "Doyle", "McCarthy", "Gallagher",
    "O'Dwyer", "Kavanagh", "Kennedy", "Lynch", "Murray", "Quinn", "Reilly",
    "Smith", "Sullivan", "Thompson", "Walsh", "White", "Wilson", "Woods",
]


def _build_name_pool():
    """Return a list of (name_type, name_value, region) tuples for all
    nation-specific name pools.
    """
    pool = []
    # Map nation_name -> (male_firsts, female_firsts, lasts, nicknames)
    # Multiple nations can share an English/Spanish pool.
    nation_pools = {
        "United States":      (ENGLISH_MALE_FIRSTS, ENGLISH_FEMALE_FIRSTS, ENGLISH_LASTS, NICKNAMES_EN),
        "United Kingdom":     (ENGLISH_MALE_FIRSTS, ENGLISH_FEMALE_FIRSTS, ENGLISH_LASTS, NICKNAMES_EN),
        "Canada":             (ENGLISH_MALE_FIRSTS, ENGLISH_FEMALE_FIRSTS, ENGLISH_LASTS, NICKNAMES_EN),
        "Australia":          (ENGLISH_MALE_FIRSTS, ENGLISH_FEMALE_FIRSTS, ENGLISH_LASTS, NICKNAMES_EN),
        "Ireland":            (IRISH_MALE_FIRSTS, IRISH_FEMALE_FIRSTS, IRISH_LASTS, NICKNAMES_EN),
        "Brazil":             (PORTUGUESE_MALE_FIRSTS, PORTUGUESE_FEMALE_FIRSTS, PORTUGUESE_LASTS, NICKNAMES_EN),
        "Portugal":           (PORTUGUESE_MALE_FIRSTS, PORTUGUESE_FEMALE_FIRSTS, PORTUGUESE_LASTS, NICKNAMES_EN),
        "Japan":              (JAPANESE_MALE_FIRSTS, JAPANESE_FEMALE_FIRSTS, JAPANESE_LASTS, NICKNAMES_EN),
        "Russia":             (RUSSIAN_MALE_FIRSTS, RUSSIAN_FEMALE_FIRSTS, RUSSIAN_LASTS, NICKNAMES_EN),
        "Dagestan":           (RUSSIAN_MALE_FIRSTS, RUSSIAN_FEMALE_FIRSTS, RUSSIAN_LASTS, NICKNAMES_EN),
        "Mexico":             (SPANISH_MALE_FIRSTS, SPANISH_FEMALE_FIRSTS, SPANISH_LASTS, NICKNAMES_EN),
        "Cuba":               (SPANISH_MALE_FIRSTS, SPANISH_FEMALE_FIRSTS, SPANISH_LASTS, NICKNAMES_EN),
        "Argentina":          (SPANISH_MALE_FIRSTS, SPANISH_FEMALE_FIRSTS, SPANISH_LASTS, NICKNAMES_EN),
        "France":             (FRENCH_MALE_FIRSTS, FRENCH_FEMALE_FIRSTS, FRENCH_LASTS, NICKNAMES_EN),
        "Germany":            (GERMAN_MALE_FIRSTS, GERMAN_FEMALE_FIRSTS, GERMAN_LASTS, NICKNAMES_EN),
        "Poland":             (POLISH_MALE_FIRSTS, POLISH_FEMALE_FIRSTS, POLISH_LASTS, NICKNAMES_EN),
        "Sweden":             (SWEDISH_MALE_FIRSTS, SWEDISH_FEMALE_FIRSTS, SWEDISH_LASTS, NICKNAMES_EN),
        "South Korea":        (KOREAN_MALE_FIRSTS, KOREAN_FEMALE_FIRSTS, KOREAN_LASTS, NICKNAMES_EN),
        "China":              (CHINESE_MALE_FIRSTS, CHINESE_FEMALE_FIRSTS, CHINESE_LASTS, NICKNAMES_EN),
        "Netherlands":        (DUTCH_MALE_FIRSTS, DUTCH_FEMALE_FIRSTS, DUTCH_LASTS, NICKNAMES_EN),
        "Nigeria":            (NIGERIAN_MALE_FIRSTS, NIGERIAN_FEMALE_FIRSTS, NIGERIAN_LASTS, NICKNAMES_EN),
    }
    seen = set()  # (name_type, name_value, region) — dedupe within nation
    for nation_name, (males, females, lasts, nicks) in nation_pools.items():
        for n in males:
            key = ("first_male", n, nation_name)
            if key not in seen:
                seen.add(key)
                pool.append(key)
        for n in females:
            key = ("first_female", n, nation_name)
            if key not in seen:
                seen.add(key)
                pool.append(key)
        for n in lasts:
            key = ("last", n, nation_name)
            if key not in seen:
                seen.add(key)
                pool.append(key)
        for n in nicks:
            key = ("nickname", n, nation_name)
            if key not in seen:
                seen.add(key)
                pool.append(key)
    return pool


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} does not exist. Run `python src/build_db.py` first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # ----------------------------------------------------------------
    # 0. Archetypes (7 style + 5 personality) — required by Phase 3
    # ----------------------------------------------------------------
    print("Seeding archetypes...")
    for name, desc, bias_json in STYLE_ARCHETYPES:
        conn.execute(
            "INSERT OR IGNORE INTO style_archetypes "
            "(name, description, attribute_bias) VALUES (?, ?, ?)",
            (name, desc, bias_json),
        )
        conn.execute(
            "UPDATE style_archetypes SET description=?, attribute_bias=? "
            "WHERE name=?",
            (desc, bias_json, name),
        )
    for name, desc, bias_json in PERSONALITY_ARCHETYPES:
        conn.execute(
            "INSERT OR IGNORE INTO personality_archetypes "
            "(name, description, trait_bias) VALUES (?, ?, ?)",
            (name, desc, bias_json),
        )
        conn.execute(
            "UPDATE personality_archetypes SET description=?, trait_bias=? "
            "WHERE name=?",
            (desc, bias_json, name),
        )
    conn.commit()
    sa_count = conn.execute("SELECT COUNT(*) FROM style_archetypes").fetchone()[0]
    pa_count = conn.execute("SELECT COUNT(*) FROM personality_archetypes").fetchone()[0]
    print(f"  Style archetypes: {sa_count}")
    print(f"  Personality archetypes: {pa_count}")

    # ----------------------------------------------------------------
    # 1. Nations
    # ----------------------------------------------------------------
    print("Seeding nations...")
    n_nations = 0
    for name, language, mma_culture in NATIONS:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO nations (name, language) VALUES (?, ?)",
                (name, language),
            )
            n_nations += conn.total_changes  # rough counter
        except sqlite3.IntegrityError as e:
            print(f"  SKIP nation {name!r}: {e}")
    conn.commit()
    nation_count = conn.execute("SELECT COUNT(*) FROM nations").fetchone()[0]
    print(f"  Nations: {nation_count}")

    # ----------------------------------------------------------------
    # 2. Regions
    # ----------------------------------------------------------------
    print("Seeding regions...")
    for nation_name, region_name, style_prefs, market_growth in REGIONS:
        # Look up nation_id
        nid = conn.execute(
            "SELECT nation_id FROM nations WHERE name=?", (nation_name,)
        ).fetchone()
        if nid is None:
            print(f"  SKIP region {region_name!r}: nation {nation_name!r} not found")
            continue
        nation_id = nid[0]
        try:
            conn.execute(
                "INSERT OR IGNORE INTO regions (nation_id, name, style_preferences, market_growth) "
                "VALUES (?, ?, ?, ?)",
                (nation_id, region_name, style_prefs, market_growth),
            )
        except sqlite3.IntegrityError as e:
            print(f"  SKIP region {region_name!r}: {e}")
    conn.commit()
    region_count = conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0]
    print(f"  Regions: {region_count}")

    # ----------------------------------------------------------------
    # 3. Cities + Markets + Venues
    # ----------------------------------------------------------------
    print("Seeding cities, markets, venues...")
    for region_name, city_name, population in CITIES:
        rid = conn.execute(
            "SELECT region_id FROM regions WHERE name=?", (region_name,)
        ).fetchone()
        if rid is None:
            print(f"  SKIP city {city_name!r}: region {region_name!r} not found")
            continue
        region_id = rid[0]
        nation_id = conn.execute(
            "SELECT nation_id FROM regions WHERE region_id=?", (region_id,)
        ).fetchone()[0]
        # Insert city (idempotent via UNIQUE name? Not in schema — so
        # we check existence first)
        existing = conn.execute(
            "SELECT city_id FROM cities WHERE name=? AND region_id=?",
            (city_name, region_id),
        ).fetchone()
        if existing:
            city_id = existing[0]
        else:
            cur = conn.execute(
                "INSERT INTO cities (nation_id, region_id, name, population) "
                "VALUES (?, ?, ?, ?)",
                (nation_id, region_id, city_name, population),
            )
            city_id = cur.lastrowid
        # Market: one per city. heat_level derived from population
        # (bigger city = hotter market, log-scaled + clamped 30-95).
        import math
        heat = max(30, min(95, int(30 + math.log10(max(10000, population)) * 8)))
        market_type = "major" if population > 1000000 else ("mid" if population > 200000 else "small")
        conn.execute(
            "INSERT OR IGNORE INTO markets (city_id, market_type, heat_level) "
            "VALUES (?, ?, ?)",
            (city_id, market_type, heat),
        )
        # Venues: 1-3 per major city, 1 per mid/small city. Capacities
        # scaled by city population.
        n_venues = 3 if population > 1000000 else (2 if population > 200000 else 1)
        for v_idx in range(n_venues):
            venue_suffix = "" if v_idx == 0 else f" {chr(65 + v_idx)}"
            venue_name = f"{city_name} Arena{venue_suffix}" if n_venues == 1 else f"{city_name} {['Arena', 'Coliseum', 'Center'][v_idx]}"
            # Capacity: 5000-20000 for major, 2000-8000 for mid, 800-3000 for small
            if population > 1000000:
                capacity = 8000 + (v_idx * 3000) + (hash(city_name) % 5000)
            elif population > 200000:
                capacity = 3000 + (v_idx * 1500) + (hash(city_name) % 2000)
            else:
                capacity = 1000 + (hash(city_name) % 1500)
            conn.execute(
                "INSERT OR IGNORE INTO venues (city_id, name, capacity) "
                "VALUES (?, ?, ?)",
                (city_id, venue_name, capacity),
            )
    conn.commit()
    city_count = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    market_count = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    venue_count = conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
    print(f"  Cities: {city_count}")
    print(f"  Markets: {market_count}")
    print(f"  Venues: {venue_count}")

    # ----------------------------------------------------------------
    # 4. Weight classes
    # ----------------------------------------------------------------
    print("Seeding weight classes...")
    for name, gender, min_w, max_w, order in WEIGHT_CLASSES:
        # Use UNIQUE name to dedupe — but men's and women's share
        # names (e.g. "Bantamweight"). So check (name, gender) tuple.
        existing = conn.execute(
            "SELECT weight_class_id FROM weight_classes WHERE name=? AND gender=?",
            (name, gender),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO weight_classes (name, gender, min_weight_kg, max_weight_kg, display_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, gender, min_w, max_w, order),
        )
    conn.commit()
    wc_count = conn.execute("SELECT COUNT(*) FROM weight_classes").fetchone()[0]
    print(f"  Weight classes: {wc_count}")

    # ----------------------------------------------------------------
    # 5. Name pools
    # ----------------------------------------------------------------
    print("Seeding name pools...")
    name_pool = _build_name_pool()
    # Clear existing name pool entries (the test seed inserts 96 —
    # we replace them with the full ~2,500 region-tagged pool).
    conn.execute("DELETE FROM name_pools")
    for name_type, name_value, region in name_pool:
        conn.execute(
            "INSERT INTO name_pools (name_type, name_value, region) "
            "VALUES (?, ?, ?)",
            (name_type, name_value, region),
        )
    conn.commit()
    np_count = conn.execute("SELECT COUNT(*) FROM name_pools").fetchone()[0]
    print(f"  Name pool entries: {np_count}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("World seed Phase 1 complete.")
    print(f"  Nations:       {nation_count}")
    print(f"  Regions:       {region_count}")
    print(f"  Cities:        {city_count}")
    print(f"  Markets:       {market_count}")
    print(f"  Venues:        {venue_count}")
    print(f"  Weight classes: {wc_count}")
    print(f"  Name pool:     {np_count} entries")
    print("=" * 60)
    print()
    print("Next: python scripts/seed_world_phase2.py (gyms, promotions, staff)")

    conn.close()


if __name__ == "__main__":
    main()
