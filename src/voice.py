"""CAGE EMPIRE Voice / Interpretation Layer (Task 19).

THE CORE DIRECTIVE (CONVENTIONS §14):
  No raw attribute values, potential numbers, or internal ratings
  appear in the player-facing UI. All numbers pass through this
  module and are displayed as human-readable descriptors.

  Raw: potential=72, punch_power=58, chin=62
  Player sees: "Solid prospect with above-average power and a
  respectable chin."

ARCHITECTURE:
  This module is PURE — no DB access, no I/O, no side effects. It
  takes raw values (ints/floats) and returns descriptor strings.
  The caller (UI, news engine, scouting reports) is responsible
  for fetching the raw values from the DB and passing them in.

  A snapshot table (`fighter_descriptors`) caches the computed
  descriptors per fighter as JSON. The snapshot is updated on
  trigger events (camp completion, fight resolution, injury, title
  change) — NOT on every UI view. This keeps the UI fast and the
  descriptors stable until a meaningful change happens.

BANDED DESCRIPTORS (CONVENTIONS §14.3):
  Descriptors are banded into 7 tiers. A fighter whose cardio drops
  from 76 to 74 sees their descriptor change from "above-average" to
  "solid". A drop from 76 to 75 does NOT change the descriptor. This
  prevents descriptor flickering.

  Tier bands:
    90-100: elite       (top 1%)
    75-89:  strong      (top 10%)
    60-74:  capable     (top 30%)
    40-59:  average     (middle 40%)
    25-39:  limited     (bottom 30%)
    10-24:  poor        (bottom 10%)
    0-9:    abysmal     (rare — career-ending decline)

VOICE/STYLE:
  CAGE EMPIRE's voice is gritty, journalistic, present-tense. Short
  punchy phrases. No numbers. Character-driven. The player collects
  stories, not fighters — every descriptor should feel like a line
  from a fight journalist's notebook.

USAGE:
  from voice import describe_attribute, describe_potential
  desc = describe_attribute("punch_power", 85)  # → "one-punch knockout threat"
  pot_desc = describe_potential(72, scouted=True)  # → "high ceiling"
"""
import random


# ----------------------------------------------------------------
# Tier bands (CONVENTIONS §14.3). A value falls into exactly one
# tier. The tier determines which descriptor variants are available.
# ----------------------------------------------------------------
TIERS = [
    (90, 100, "elite"),
    (75, 89,  "strong"),
    (60, 74,  "capable"),
    (40, 59,  "average"),
    (25, 39,  "limited"),
    (10, 24,  "poor"),
    (0,  9,   "abysmal"),
]


def _tier_for(value):
    """Return the tier name for a given 0-100 value."""
    for lo, hi, name in TIERS:
        if lo <= value <= hi:
            return name
    return "average"  # defensive for out-of-range values


def _pick(variants, rng=None):
    """Pick a random variant from a list. Uses the provided rng or
    the global random. This adds variety so two fighters with the
    same punch_power don't get identical descriptors.
    """
    if rng is not None:
        return rng.choice(variants)
    return random.choice(variants)


# ----------------------------------------------------------------
# ATTRIBUTE DESCRIPTORS
#
# Each attribute maps to a dict of tier → list of descriptor variants.
# Variants are short phrases (3-8 words) in CAGE EMPIRE voice.
# 25 attributes × 7 tiers × 2-3 variants = ~500 descriptor strings.
# ----------------------------------------------------------------

ATTRIBUTE_DESCRIPTORS = {
    # ---- Striking (5) ----
    "punch_power": {
        "elite":    ["one-punch knockout threat", "fight-ending power in both hands", "heavy hands that end careers"],
        "strong":   ["carries real knockout power", "hits hard enough to change a fight", "heavy-handed striker"],
        "capable":  ["respectable power", "can hurt you with one shot", "above-average pop"],
        "average":  ["average power", "won't shock anyone with his hands", "serviceable striking"],
        "limited":  ["lacks stopping power", "not a threat to finish standing", "pillow-fisted"],
        "poor":     ["can't hurt a fly standing", "no power whatsoever", "pitter-patter punches"],
        "abysmal":  ["physically incapable of generating power", "withered striking"],
    },
    "punch_accuracy": {
        "elite":    ["surgical precision", "picks opponents apart with pinpoint strikes", "lands at will"],
        "strong":   ["sharp, accurate striker", "picks his shots well", "rarely wastes a punch"],
        "capable":  ["respectable accuracy", "finds his range consistently", "above-average precision"],
        "average":  ["average accuracy", "hits what's in front of him", "serviceable timing"],
        "limited":  ["struggles to find the target", "wild at times", "below-average accuracy"],
        "poor":     ["can't hit the broad side of a barn", "telegraphs everything", "wildly inaccurate"],
        "abysmal":  ["swings at air", "no hand-eye coordination"],
    },
    "kick_power": {
        "elite":    ["devastating kicks", "fight-ending head kicks", "legs like baseball bats"],
        "strong":   ["thudding low kicks", "powerful kicking game", "can finish with kicks"],
        "capable":  ["respectable kick power", "above-average kicks", "solid low kicks"],
        "average":  ["average kicking power", "serviceable kicks", "won't threaten with kicks"],
        "limited":  ["rarely kicks", "weak kicking game", "doesn't trust his kicks"],
        "poor":     ["no kicking game to speak of", "can't kick effectively"],
        "abysmal":  ["physically incapable of kicking", "no leg technique"],
    },
    "kick_accuracy": {
        "elite":    ["pinpoint kicks", "surgical kicking accuracy", "lands kicks at will"],
        "strong":   ["accurate kicker", "precise with his feet", "finds openings with kicks"],
        "capable":  ["respectable kick accuracy", "above-average precision", "solid kick placement"],
        "average":  ["average kick accuracy", "serviceable kicks", "hits what's there"],
        "limited":  ["wild with his kicks", "below-average accuracy", "telegraphs kicks"],
        "poor":     ["can't land a kick", "wildly inaccurate kicker"],
        "abysmal":  ["no kick technique", "can't find the target with his feet"],
    },
    "head_movement": {
        "elite":    ["ghost-like head movement", "makes opponents miss by inches", "slips and counters with ease"],
        "strong":   ["excellent head movement", "slips punches well", "hard to hit clean"],
        "capable":  ["respectable head movement", "above-average defense", "slips the big ones"],
        "average":  ["average head movement", "takes some to give some", "serviceable defense"],
        "limited":  ["stiff defensively", "below-average head movement", "takes too many clean"],
        "poor":     ["no head movement", "stationary target", "easy to hit"],
        "abysmal":  ["human punching bag", "can't get out of the way"],
    },

    # ---- Range / Footwork (4) ----
    "footwork": {
        "elite":    ["elite footwork", "dances around opponents", "controls distance masterfully"],
        "strong":   ["excellent footwork", "moves well in and out", "controls range effectively"],
        "capable":  ["respectable footwork", "above-average movement", "solid ring generalship"],
        "average":  ["average footwork", "gets where he needs to go", "serviceable movement"],
        "limited":  ["flat-footed", "below-average footwork", "struggles with distance"],
        "poor":     ["no footwork", "planted flat", "easy to corner"],
        "abysmal":  ["can't move", "statue in the cage"],
    },
    "clinch_striking": {
        "elite":    ["devastating in the clinch", "punishes opponents up close", "elite dirty boxing"],
        "strong":   ["excellent clinch striking", "dangerous up close", "strong dirty boxing"],
        "capable":  ["respectable clinch work", "above-average inside", "solid in tight"],
        "average":  ["average clinch striking", "serviceable inside", "holds his own in tight"],
        "limited":  ["weak in the clinch", "below-average inside", "struggles up close"],
        "poor":     ["no clinch striking", "ineffective inside", "averse to the clinch"],
        "abysmal":  ["useless in the clinch", "can't work inside"],
    },
    "clinch_offense": {
        "elite":    ["elite clinch offense", "throws opponents around", "dominates in the clinch"],
        "strong":   ["strong clinch offense", "controls opponents inside", "effective clinch work"],
        "capable":  ["respectable clinch offense", "above-average inside", "can work in the clinch"],
        "average":  ["average clinch offense", "serviceable inside", "holds his own"],
        "limited":  ["limited clinch offense", "below-average inside", "struggles to generate offense"],
        "poor":     ["no clinch offense", "ineffective inside", "can't work in tight"],
        "abysmal":  ["useless in the clinch", "no inside game"],
    },
    "clinch_defense": {
        "elite":    ["impenetrable clinch defense", "impossible to hold", "breaks free at will"],
        "strong":   ["excellent clinch defense", "hard to control", "breaks grips well"],
        "capable":  ["respectable clinch defense", "above-average inside", "can escape the clinch"],
        "average":  ["average clinch defense", "serviceable inside", "holds his own"],
        "limited":  ["struggles in the clinch", "below-average defense", "gets stuck inside"],
        "poor":     ["no clinch defense", "gets dominated inside", "can't escape"],
        "abysmal":  ["helpless in the clinch", "ragdoll inside"],
    },

    # ---- Grappling (7) ----
    "takedown_offense": {
        "elite":    ["elite takedown artist", "takes down anyone", "unstoppable wrestling"],
        "strong":   ["excellent takedowns", "strong wrestling", "can take down most fighters"],
        "capable":  ["respectable takedowns", "above-average wrestling", "can get the fight down"],
        "average":  ["average takedowns", "serviceable wrestling", "can take down lesser grapplers"],
        "limited":  ["limited takedowns", "below-average wrestling", "struggles to get it down"],
        "poor":     ["no takedown game", "can't wrestle", "ineffective takedowns"],
        "abysmal":  ["can't take anyone down", "no wrestling whatsoever"],
    },
    "takedown_defense": {
        "elite":    ["impenetrable takedown defense", "impossible to take down", "brick wall wrestling"],
        "strong":   ["excellent takedown defense", "hard to get down", "sprawls well"],
        "capable":  ["respectable takedown defense", "above-average sprawl", "can stay standing"],
        "average":  ["average takedown defense", "serviceable sprawl", "can defend lesser wrestlers"],
        "limited":  ["limited takedown defense", "below-average sprawl", "can be taken down"],
        "poor":     ["no takedown defense", "easy to take down", "can't sprawl"],
        "abysmal":  ["ragdoll on the mat", "can't defend a takedown"],
    },
    "top_control": {
        "elite":    ["elite top control", "smothers opponents", "once on top, stays on top"],
        "strong":   ["excellent top control", "dominant on top", "strong ground and pound position"],
        "capable":  ["respectable top control", "above-average on top", "can hold position"],
        "average":  ["average top control", "serviceable on top", "holds his own"],
        "limited":  ["limited top control", "below-average on top", "struggles to hold position"],
        "poor":     ["no top control", "can't maintain position", "gets reversed easily"],
        "abysmal":  ["helpless on top", "can't hold anyone down"],
    },
    "bottom_game": {
        "elite":    ["dangerous off his back", "elite guard player", "submits people from the bottom"],
        "strong":   ["excellent bottom game", "active guard", "dangerous off his back"],
        "capable":  ["respectable bottom game", "above-average guard", "can work off his back"],
        "average":  ["average bottom game", "serviceable guard", "survives on the bottom"],
        "limited":  ["limited bottom game", "below-average guard", "struggles off his back"],
        "poor":     ["no bottom game", "turtles up", "helpless on the bottom"],
        "abysmal":  ["fish on the deck", "can't do anything off his back"],
    },
    "submission_offense": {
        "elite":    ["elite submission artist", "tap-or-pass specialist", "submission machine"],
        "strong":   ["dangerous submission game", "always hunting subs", "can finish on the ground"],
        "capable":  ["respectable submissions", "above-average ground game", "can catch a sub"],
        "average":  ["average submissions", "serviceable ground game", "knows the basics"],
        "limited":  ["limited submissions", "below-average ground game", "rarely threatens"],
        "poor":     ["no submission game", "can't finish on the ground", "ineffective subs"],
        "abysmal":  ["no ground technique", "can't submit anyone"],
    },
    "submission_defense": {
        "elite":    ["impossible to submit", "elite submission defense", "never gets caught"],
        "strong":   ["excellent submission defense", "hard to catch", "knows the escapes"],
        "capable":  ["respectable submission defense", "above-average awareness", "can defend subs"],
        "average":  ["average submission defense", "serviceable awareness", "knows the basics"],
        "limited":  ["limited submission defense", "below-average awareness", "can get caught"],
        "poor":     ["poor submission defense", "easy to submit", "taps quickly"],
        "abysmal":  ["human noodle", "submits to anything"],
    },
    "scramble_ability": {
        "elite":    ["elite scrambler", "wins every scramble", "impossible to hold down"],
        "strong":   ["excellent scrambler", "quick to reverse", "dangerous in transitions"],
        "capable":  ["respectable scrambler", "above-average in transitions", "can win scrambles"],
        "average":  ["average scrambler", "serviceable in transitions", "holds his own"],
        "limited":  ["limited scrambler", "below-average in transitions", "loses scrambles"],
        "poor":     ["no scramble ability", "gets stuck in bad positions", "can't reverse"],
        "abysmal":  ["helpless in scrambles", "can't regain position"],
    },

    # ---- Cage wrestling (1) ----
    "cage_wrestling": {
        "elite":    ["elite cage wrestler", "dominates against the fence", "unstoppable in the clinch"],
        "strong":   ["excellent cage work", "strong against the fence", "effective wall-and-mall"],
        "capable":  ["respectable cage wrestling", "above-average against the fence", "can work the cage"],
        "average":  ["average cage wrestling", "serviceable against the fence", "holds his own"],
        "limited":  ["limited cage wrestling", "below-average against the fence", "gets pushed around"],
        "poor":     ["no cage wrestling", "ineffective against the fence", "gets dominated in the clinch"],
        "abysmal":  ["helpless against the fence", "can't work the cage"],
    },

    # ---- Physical (6) ----
    "cardio": {
        "elite":    ["endless gas tank", "never tires", "fights at the same pace for 25 minutes"],
        "strong":   ["excellent cardio", "strong late in fights", "rarely fades"],
        "capable":  ["respectable cardio", "above-average stamina", "can go the distance"],
        "average":  ["average cardio", "serviceable stamina", "fades in deep waters"],
        "limited":  ["limited cardio", "below-average stamina", "gasses in the championship rounds"],
        "poor":     ["poor cardio", "fades early", "gasses by round 2"],
        "abysmal":  ["no gas tank", "exhausted after one round", "cardio is a liability"],
    },
    "recovery_rate": {
        "elite":    ["recovers instantly", "elite recovery", "bounces back between rounds"],
        "strong":   ["excellent recovery", "recovers quickly", "strong between rounds"],
        "capable":  ["respectable recovery", "above-average between rounds", "can bounce back"],
        "average":  ["average recovery", "serviceable between rounds", "recovers at a normal pace"],
        "limited":  ["limited recovery", "below-average between rounds", "slow to recover"],
        "poor":     ["poor recovery", "doesn't recover between rounds", "worn down easily"],
        "abysmal":  ["no recovery", "once tired, stays tired"],
    },
    "speed_explosiveness": {
        "elite":    ["explosive athlete", "elite speed", "lightning-fast twitch"],
        "strong":   ["explosive", "quick-twitch", "above-average speed"],
        "capable":  ["respectable explosiveness", "above-average speed", "can explode into entries"],
        "average":  ["average speed", "serviceable explosiveness", "not particularly quick"],
        "limited":  ["limited explosiveness", "below-average speed", "slow-twitch"],
        "poor":     ["slow", "lacks explosiveness", "can't close the distance"],
        "abysmal":  ["glacially slow", "no explosiveness whatsoever"],
    },
    "strength": {
        "elite":    ["freakish strength", "overpowers everyone", "elite physical strength"],
        "strong":   ["very strong", "overpowers most", "above-average strength"],
        "capable":  ["respectable strength", "above-average power", "can muscle opponents"],
        "average":  ["average strength", "serviceable physically", "holds his own"],
        "limited":  ["limited strength", "below-average physically", "gets overpowered"],
        "poor":     ["weak", "lacks physical strength", "gets bullied"],
        "abysmal":  ["no strength", "overpowered by everyone"],
    },
    "durability": {
        "elite":    ["iron body", "can't be hurt", "walks through everything"],
        "strong":   ["very durable", "hard to hurt", "takes a beating and keeps coming"],
        "capable":  ["respectable durability", "above-average toughness", "can take a shot"],
        "average":  ["average durability", "serviceable toughness", "can be hurt by big shots"],
        "limited":  ["limited durability", "below-average toughness", "wobbles easily"],
        "poor":     ["fragile", "hurt by clean shots", "can't take a beating"],
        "abysmal":  ["glass body", "injured by everything", "can't absorb punishment"],
    },
    "flexibility": {
        "elite":    ["contortionist", "elite flexibility", "rubber joints"],
        "strong":   ["very flexible", "above-average range of motion", "limber"],
        "capable":  ["respectable flexibility", "above-average mobility", "can work his guard"],
        "average":  ["average flexibility", "serviceable mobility", "normal range of motion"],
        "limited":  ["limited flexibility", "below-average mobility", "stiff"],
        "poor":     ["inflexible", "stiff joints", "can't work from guard"],
        "abysmal":  ["frozen", "no flexibility whatsoever"],
    },

    # ---- Mental (4) ----
    "fight_iq": {
        "elite":    ["master strategist", "elite fight IQ", "chess player in the cage"],
        "strong":   ["smart fighter", "excellent game planning", "high fight IQ"],
        "capable":  ["respectable fight IQ", "above-average awareness", "makes good adjustments"],
        "average":  ["average fight IQ", "serviceable awareness", "follows a game plan"],
        "limited":  ["limited fight IQ", "below-average awareness", "makes mistakes"],
        "poor":     ["low fight IQ", "no strategy", "fights on instinct alone"],
        "abysmal":  ["no fight IQ", "makes the same mistakes repeatedly"],
    },
    "chin": {
        "elite":    ["iron chin", "can't be knocked out", "walks through bombs"],
        "strong":   ["excellent chin", "hard to rock", "takes clean shots and keeps coming"],
        "capable":  ["respectable chin", "above-average durability", "can take a shot"],
        "average":  ["average chin", "serviceable durability", "can be rocked by big shots"],
        "limited":  ["limited chin", "below-average durability", "wobbles from clean shots"],
        "poor":     ["glass chin", "hurt by anything clean", "one shot away from sleeping"],
        "abysmal":  ["no chin at all", "knocked out by glancing blows"],
    },
    "adaptability": {
        "elite":    ["adapts to anything", "elite adjustments", "can fight any style"],
        "strong":   ["very adaptable", "makes mid-fight adjustments", "above-average flexibility"],
        "capable":  ["respectable adaptability", "above-average adjustments", "can change plans"],
        "average":  ["average adaptability", "serviceable adjustments", "sticks to the game plan"],
        "limited":  ["limited adaptability", "below-average adjustments", "struggles when plan A fails"],
        "poor":     ["one-trick pony", "can't adjust", "fights the same way every time"],
        "abysmal":  ["no adaptability", "frozen when things go wrong"],
    },
}


# ----------------------------------------------------------------
# PERSONALITY DESCRIPTORS
#
# 20 personality traits × 7 tiers × 2-3 variants = ~400 strings.
# ----------------------------------------------------------------

PERSONALITY_DESCRIPTORS = {
    "aggression": {
        "elite":    ["comes forward like a freight train", "relentless pressure fighter", "never stops coming"],
        "strong":   ["highly aggressive", "constant forward pressure", "pushes the pace"],
        "capable":  ["willing to engage", "above-average aggression", "comes to fight"],
        "average":  ["measured aggression", "picks his moments", "average pace"],
        "limited":  ["passive at times", "below-average aggression", "waits too much"],
        "poor":     ["reluctant to engage", "fights not to lose", "backpedals constantly"],
        "abysmal":  ["completely passive", "won't engage at all"],
    },
    "composure": {
        "elite":    ["ice in his veins", "never rattled", "unflappable under pressure"],
        "strong":   ["very composed", "stays calm in chaos", "above-average poise"],
        "capable":  ["respectable composure", "above-average poise", "keeps his head"],
        "average":  ["average composure", "serviceable poise", "can be rattled"],
        "limited":  ["limited composure", "below-average poise", "panics under pressure"],
        "poor":     ["crumbles under pressure", "easily rattled", "loses his cool"],
        "abysmal":  ["freezes in the cage", "completely falls apart"],
    },
    "morale": {
        "elite":    ["riding high", "peak confidence", "believes he's unbeatable"],
        "strong":   ["high morale", "confident", "in a good headspace"],
        "capable":  ["respectable morale", "above-average confidence", "in good spirits"],
        "average":  ["average morale", "steady mindset", "neither up nor down"],
        "limited":  ["limited morale", "below-average confidence", "second-guessing himself"],
        "poor":     ["low morale", "confidence shot", "in a slump"],
        "abysmal":  ["completely broken", "wants to quit", "no confidence left"],
    },
    "risk_taking": {
        "elite":    ["high-risk, high-reward", "lives on the edge", "goes for broke"],
        "strong":   ["willing to take risks", "above-average gambles", "not afraid to try anything"],
        "capable":  ["respectable risk-taking", "calculated gambles", "above-average boldness"],
        "average":  ["average risk tolerance", "plays it safe when needed", "balanced approach"],
        "limited":  ["risk-averse", "below-average boldness", "plays not to lose"],
        "poor":     ["completely conservative", "never takes a chance", "fights scared"],
        "abysmal":  ["paralyzed by caution", "won't try anything"],
    },
    "killer_instinct": {
        "elite":    ["smells blood and attacks", "elite finisher", "doesn't let opponents off the hook"],
        "strong":   ["strong killer instinct", "finishes when he hurts you", "above-average finishing"],
        "capable":  ["respectable finishing instinct", "above-average killer instinct", "can close the show"],
        "average":  ["average finishing instinct", "serviceable closer", "sometimes lets them off"],
        "limited":  ["limited killer instinct", "below-average finishing", "rarely closes the show"],
        "poor":     ["no killer instinct", "can't finish a hurt opponent", "lets them recover"],
        "abysmal":  ["no finishing instinct", "couldn't finish a sandwich"],
    },
    "grit": {
        "elite":    ["never quits", "elite toughness", "fights through anything"],
        "strong":   ["very gritty", "tough as nails", "above-average heart"],
        "capable":  ["respectable grit", "above-average toughness", "won't back down"],
        "average":  ["average grit", "serviceable toughness", "can dig deep when needed"],
        "limited":  ["limited grit", "below-average toughness", "folds when hurt"],
        "poor":     ["quits easily", "no heart", "taps to strikes"],
        "abysmal":  ["no grit at all", "gives up at the first sign of trouble"],
    },
    "discipline": {
        "elite":    ["elite discipline", "never deviates from the game plan", "machine-like execution"],
        "strong":   ["very disciplined", "sticks to the plan", "above-average focus"],
        "capable":  ["respectable discipline", "above-average focus", "follows instructions"],
        "average":  ["average discipline", "serviceable focus", "can be drawn into mistakes"],
        "limited":  ["limited discipline", "below-average focus", "loses the game plan"],
        "poor":     ["no discipline", "fights emotionally", "ignores the corner"],
        "abysmal":  ["completely undisciplined", "does whatever he wants"],
    },
    "patience": {
        "elite":    ["endless patience", "waits for the perfect moment", "never rushes"],
        "strong":   ["very patient", "above-average timing", "doesn't force anything"],
        "capable":  ["respectable patience", "above-average timing", "can wait for openings"],
        "average":  ["average patience", "serviceable timing", "sometimes rushes"],
        "limited":  ["limited patience", "below-average timing", "forces things"],
        "poor":     ["no patience", "rushes everything", "fights in a hurry"],
        "abysmal":  ["completely reckless", "no concept of timing"],
    },
    "ambition": {
        "elite":    ["wants to be the greatest", "elite ambition", "will do anything to win"],
        "strong":   ["very ambitious", "above-average drive", "hungry for greatness"],
        "capable":  ["respectable ambition", "above-average drive", "wants to climb"],
        "average":  ["average ambition", "serviceable drive", "content where he is"],
        "limited":  ["limited ambition", "below-average drive", "just happy to be here"],
        "poor":     ["no ambition", "going through the motions", "collects a paycheck"],
        "abysmal":  ["completely apathetic", "doesn't care about winning"],
    },
    "loyalty": {
        "elite":    ["fiercely loyal", "would die for his team", "elite loyalty"],
        "strong":   ["very loyal", "above-average dedication", "sticks with his people"],
        "capable":  ["respectable loyalty", "above-average dedication", "team player"],
        "average":  ["average loyalty", "serviceable dedication", "goes where the money is"],
        "limited":  ["limited loyalty", "below-average dedication", "will jump ship"],
        "poor":     ["no loyalty", "mercenary", "betrays his team"],
        "abysmal":  ["completely disloyal", "would sell out anyone"],
    },
    "charisma": {
        "elite":    ["magnetic personality", "fans love him", "elite star power"],
        "strong":   ["very charismatic", "above-average star power", "draws a crowd"],
        "capable":  ["respectable charisma", "above-average appeal", "fans like him"],
        "average":  ["average charisma", "serviceable appeal", "doesn't move the needle"],
        "limited":  ["limited charisma", "below-average appeal", "boring to fans"],
        "poor":     ["no charisma", "fans don't care", "invisible personality"],
        "abysmal":  ["actively unlikable", "fans change the channel"],
    },
    "attention_seeking": {
        "elite":    ["attention magnet", "creates controversy everywhere", "elite self-promoter"],
        "strong":   ["loves the spotlight", "above-average showmanship", "creates drama"],
        "capable":  ["respectable showmanship", "above-average promotion", "knows how to sell a fight"],
        "average":  ["average self-promotion", "serviceable hype", "doesn't seek attention"],
        "limited":  ["avoids the spotlight", "below-average promotion", "shy with media"],
        "poor":     ["hates attention", "no self-promotion", "invisible to media"],
        "abysmal":  ["actively avoids media", "no interest in promotion"],
    },
    "coachability": {
        "elite":    ["sponge for coaching", "elite learner", "absorbs everything"],
        "strong":   ["very coachable", "above-average learner", "listens to his corner"],
        "capable":  ["respectable coachability", "above-average learner", "takes instruction"],
        "average":  ["average coachability", "serviceable learner", "sometimes ignores advice"],
        "limited":  ["limited coachability", "below-average learner", "thinks he knows better"],
        "poor":     ["uncoachable", "ignores his corner", "does his own thing"],
        "abysmal":  ["actively hostile to coaching", "won't listen to anyone"],
    },
    "professionalism": {
        "elite":    ["consummate professional", "elite work ethic", "model fighter"],
        "strong":   ["very professional", "above-average work ethic", "reliable"],
        "capable":  ["respectable professionalism", "above-average work ethic", "does things right"],
        "average":  ["average professionalism", "serviceable work ethic", "shows up"],
        "limited":  ["limited professionalism", "below-average work ethic", "misses camp"],
        "poor":     ["unprofessional", "no work ethic", "headache for the promotion"],
        "abysmal":  ["complete disaster", "can't be relied on for anything"],
    },
    "ego": {
        "elite":    ["massive ego", "thinks he's god's gift", "insufferably arrogant"],
        "strong":   ["big ego", "above-average arrogance", "full of himself"],
        "capable":  ["respectable ego", "above-average confidence", "believes in himself"],
        "average":  ["average ego", "balanced self-image", "neither humble nor arrogant"],
        "limited":  ["limited ego", "below-average confidence", "self-deprecating"],
        "poor":     ["no ego", "low self-esteem", "doesn't believe in himself"],
        "abysmal":  ["completely self-loathing", "no self-worth"],
    },
    "resilience": {
        "elite":    ["bounces back from anything", "elite resilience", "never stays down"],
        "strong":   ["very resilient", "above-average bounce-back", "comes back from adversity"],
        "capable":  ["respectable resilience", "above-average recovery", "can bounce back"],
        "average":  ["average resilience", "serviceable recovery", "can be broken by setbacks"],
        "limited":  ["limited resilience", "below-average recovery", "struggles after losses"],
        "poor":     ["no resilience", "crumbles after setbacks", "never recovers"],
        "abysmal":  ["completely fragile", "one loss away from retirement"],
    },
    "sportsmanship": {
        "elite":    ["class act", "elite sportsmanship", "respects everyone"],
        "strong":   ["very sportsmanlike", "above-average class", "respects opponents"],
        "capable":  ["respectable sportsmanship", "above-average class", "generally respectful"],
        "average":  ["average sportsmanship", "serviceable class", "can be salty"],
        "limited":  ["limited sportsmanship", "below-average class", "sore loser"],
        "poor":     ["no sportsmanship", "disrespects opponents", "dirty fighter"],
        "abysmal":  ["completely classless", "cheats whenever possible"],
    },
    "travel_comfort": {
        "elite":    ["travels like a veteran", "elite road warrior", "unfazed by time zones"],
        "strong":   ["very comfortable traveling", "above-average adaptability", "handles road fights well"],
        "capable":  ["respectable travel comfort", "above-average adaptability", "can fight on the road"],
        "average":  ["average travel comfort", "serviceable adaptability", "prefers home"],
        "limited":  ["limited travel comfort", "below-average adaptability", "struggles on the road"],
        "poor":     ["hates traveling", "poor road fighter", "can't adapt to new environments"],
        "abysmal":  ["can't fight outside his home city", "completely homesick"],
    },
    "focus": {
        "elite":    ["laser-focused", "elite concentration", "never distracted"],
        "strong":   ["very focused", "above-average concentration", "stays in the moment"],
        "capable":  ["respectable focus", "above-average concentration", "can maintain attention"],
        "average":  ["average focus", "serviceable concentration", "can be distracted"],
        "limited":  ["limited focus", "below-average concentration", "loses attention"],
        "poor":     ["no focus", "easily distracted", "mind wanders"],
        "abysmal":  ["completely scattered", "can't concentrate on anything"],
    },
    "fatigue_tolerance": {
        "elite":    ["thrives when tired", "elite fatigue tolerance", "fights better the deeper it goes"],
        "strong":   ["very fatigue-tolerant", "above-average stamina", "doesn't slow down when tired"],
        "capable":  ["respectable fatigue tolerance", "above-average stamina", "can fight through fatigue"],
        "average":  ["average fatigue tolerance", "serviceable stamina", "slows when tired"],
        "limited":  ["limited fatigue tolerance", "below-average stamina", "folds when tired"],
        "poor":     ["no fatigue tolerance", "falls apart when tired", "can't fight through fatigue"],
        "abysmal":  ["completely collapses when tired", "useless after round 1"],
    },
}


# ----------------------------------------------------------------
# POTENTIAL DESCRIPTORS
#
# Potential is HIDDEN from the player until scouted (Task 18).
# When scouted, the descriptor reflects the scout's estimate
# (with noise). When unscouted, the player sees nothing.
# ----------------------------------------------------------------

POTENTIAL_DESCRIPTORS = {
    "elite":    ["generational talent ceiling", "future champion potential", "elite upside"],
    "strong":   ["high ceiling", "contender potential", "above-average upside"],
    "capable":  ["solid potential", "respectable ceiling", "can develop into a contender"],
    "average":  ["average potential", "limited ceiling", "what you see is what you get"],
    "limited":  ["limited potential", "low ceiling", "unlikely to improve much"],
    "poor":     ["minimal potential", "very low ceiling", "already at his peak"],
    "abysmal":  ["no potential", "declining", "past his prime"],
}


def describe_potential(potential, scouted=False, rng=None):
    """Describe a fighter's potential.

    Args:
        potential: 0-100 integer. The fighter's growth ceiling.
        scouted: if False, returns None (potential is hidden from
            the player until scouted via Task 18). If True, returns
            the descriptor (the scout's estimate).
        rng: optional random.Random for variant selection.

    Returns:
        A descriptor string, or None if not scouted.
    """
    if not scouted:
        return None
    tier = _tier_for(potential)
    variants = POTENTIAL_DESCRIPTORS.get(tier, POTENTIAL_DESCRIPTORS["average"])
    return _pick(variants, rng)


# ----------------------------------------------------------------
# CAREER DESCRIPTORS
#
# Based on observable career state: age, record, title reigns,
# win/loss streaks, career_health. Does NOT reveal hidden potential.
# ----------------------------------------------------------------

def describe_career_stage(age, record_wins, record_losses, record_draws,
                          is_champion=False, title_reigns=0,
                          win_streak=0, loss_streak=0, rng=None):
    """Describe a fighter's career stage in one phrase.

    Based on observable state only (age + record + title status +
    streaks). Does NOT reveal hidden potential.

    Returns a short phrase like "reigning champion", "top prospect",
    "grizzled veteran", "journeyman gatekeeper", etc.
    """
    total_fights = record_wins + record_losses + record_draws
    if is_champion:
        if title_reigns >= 3:
            return _pick(["dominant champion", "reigning titleholder", "multi-time champ"], rng)
        return _pick(["reigning champion", "current titleholder", "champ"], rng)
    if age <= 23 and total_fights <= 8:
        return _pick(["top prospect", "young gun", "rising prospect", "blue-chip prospect"], rng)
    if age >= 36 and total_fights >= 30:
        return _pick(["grizzled veteran", "battle-tested veteran", "wily veteran"], rng)
    if loss_streak >= 3 and record_wins >= 10:
        return _pick(["fallen contender", "sliding veteran", "former contender"], rng)
    if age >= 33 and win_streak >= 3:
        return _pick(["late bloomer", "veteran on a roll", "resurgent contender"], rng)
    if total_fights >= 20 and 0.35 <= record_wins / max(1, total_fights) <= 0.65:
        return _pick(["journeyman", "gatekeeper", "mid-card veteran"], rng)
    if total_fights >= 15:
        return _pick(["seasoned competitor", "veteran fighter", "experienced hand"], rng)
    if age <= 27 and total_fights <= 12:
        return _pick(["developing prospect", "up-and-comer", "contender on the rise"], rng)
    return _pick(["roster fighter", "active competitor", "promotion fighter"], rng)


def describe_career_health(health, rng=None):
    """Describe a fighter's career health (0-100)."""
    if health >= 90:
        return _pick(["in peak condition", "fighting fit", "healthy and active"], rng)
    if health >= 70:
        return _pick(["minor wear and tear", "battling some injuries", "showing signs of age"], rng)
    if health >= 50:
        return _pick(["beaten up", "battling injuries", "worn down"], rng)
    if health >= 30:
        return _pick(["battered", "seriously degraded", "one fight from retirement"], rng)
    return _pick(["completely shot", "should retire", "physically broken"], rng)


# ----------------------------------------------------------------
# OVERALL FIGHTER DESCRIPTION
#
# A one-sentence summary combining career stage + key attributes.
# Used in fighter profile headers, scouting reports, news intros.
# ----------------------------------------------------------------

# Map style_archetype_name → natural noun phrase for use in summaries.
# "Balanced" doesn't work as a noun ("the 32-year-old balanced" reads
# awkwardly); "well-rounded fighter" does.
_ARCHETYPE_NOUN = {
    "Balanced":              "well-rounded fighter",
    "Striker":               "striker",
    "Grappler":              "grappler",
    "Wrestler":              "wrestler",
    "Brawler":               "brawler",
    "Counter-Striker":       "counter-striker",
    "Submission Specialist": "submission specialist",
}


def describe_overall(fighter_data, rng=None):
    """Build a one-sentence overall description of a fighter.

    Args:
        fighter_data: dict with keys:
            - first_name, last_name, nickname (optional)
            - age, record_wins, record_losses, record_draws
            - is_champion, title_reigns, win_streak, loss_streak
            - career_health
            - style_archetype_name
            - key_attributes: dict of {attr_name: value} for the
              fighter's top 3 attributes (used to flavor the summary)
        rng: optional random.Random

    Returns:
        A one-sentence description like:
        "John Vale is a striker with one-punch knockout threat and an
        excellent chin, riding a three-fight win streak, currently a
        seasoned competitor."

    v2.10.0 (FIX-VoiceRep, §14): the OLD output embedded raw age
    ("28-year-old") and raw streak counts ("3-fight win streak") —
    both §14 violations (no raw numbers in player-facing text). The
    age is dropped entirely (the career_stage descriptor at the end
    already encodes age + record + streaks as a human-readable
    phrase), and the streak counts are converted to word form via
    the new _num_word helper. The result is fully digit-free while
    preserving the original semantic content.
    """
    name = fighter_data.get("first_name", "") + " " + fighter_data.get("last_name", "")
    if fighter_data.get("nickname"):
        name += f" '{fighter_data['nickname']}'"
    name = name.strip()
    age = fighter_data.get("age", 30)
    stage = describe_career_stage(
        age,
        fighter_data.get("record_wins", 0),
        fighter_data.get("record_losses", 0),
        fighter_data.get("record_draws", 0),
        fighter_data.get("is_champion", False),
        fighter_data.get("title_reigns", 0),
        fighter_data.get("win_streak", 0),
        fighter_data.get("loss_streak", 0),
        rng,
    )
    sa_name = fighter_data.get("style_archetype_name", "Balanced")
    sa_noun = _ARCHETYPE_NOUN.get(sa_name, "fighter")
    # Build the summary. v2.10.0: no raw age digit — the career_stage
    # descriptor (appended at the end) already conveys age + record +
    # streaks as a human phrase like "grizzled veteran" or "top
    # prospect".
    parts = [f"{name} is a {sa_noun}"]
    # Add 1-2 key attribute descriptors if available
    key_attrs = fighter_data.get("key_attributes", {})
    if key_attrs:
        attr_descs = []
        for attr_name, value in list(key_attrs.items())[:2]:
            desc = describe_attribute(attr_name, value, rng)
            if desc:
                attr_descs.append(desc)
        if attr_descs:
            parts.append("with " + " and ".join(attr_descs))
    # Add streak if notable — word-form (no raw digits per §14).
    ws = fighter_data.get("win_streak", 0)
    ls = fighter_data.get("loss_streak", 0)
    if ws >= 3:
        parts.append(f"riding a {_num_word(ws)}-fight win streak")
    elif ls >= 3:
        parts.append(f"on a {_num_word(ls)}-fight skid")
    # Add career stage at the end
    parts.append(f"currently {stage}")
    return ", ".join(parts) + "."


# Small word-form helper for streak counts in describe_overall.
# Covers the realistic streak range (1-12); larger streaks get a
# generic "long" phrase. Kept private — voice.py exposes the rich
# ATTRIBUTE/PERSONALITY/CAREER descriptors as the public API; this
# helper is internal to describe_overall's sentence builder.
_NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve",
}


def _num_word(n):
    """Convert a small int to its word form for digit-free text.

    For numbers > 12, returns 'a long' so the text stays readable
    without using digit characters (e.g., 'riding a long win streak'
    instead of 'riding a 17-fight win streak').
    """
    if n in _NUM_WORDS:
        return _NUM_WORDS[n]
    return "a long"


# ----------------------------------------------------------------
# PUBLIC API — attribute + personality descriptors
# ----------------------------------------------------------------

def describe_attribute(attr_name, value, rng=None):
    """Describe a single attribute value.

    Args:
        attr_name: one of the 25 attribute names (e.g. "punch_power").
        value: 0-100 integer.
        rng: optional random.Random for variant selection.

    Returns:
        A descriptor string, or "unknown attribute" if the attr_name
        is not recognized.
    """
    tier = _tier_for(value)
    variants = ATTRIBUTE_DESCRIPTORS.get(attr_name, {}).get(tier)
    if not variants:
        return f"{tier} {attr_name.replace('_', ' ')}"
    return _pick(variants, rng)


def describe_personality(trait_name, value, rng=None):
    """Describe a single personality trait value.

    Args:
        trait_name: one of the 20 personality trait names.
        value: 0-100 integer.
        rng: optional random.Random for variant selection.

    Returns:
        A descriptor string.
    """
    tier = _tier_for(value)
    variants = PERSONALITY_DESCRIPTORS.get(trait_name, {}).get(tier)
    if not variants:
        return f"{tier} {trait_name.replace('_', ' ')}"
    return _pick(variants, rng)


# ----------------------------------------------------------------
# SNAPSHOT BUILDER
#
# Builds a complete descriptor snapshot for a fighter — all 25
# attribute descriptors + all 20 personality descriptors + career
# stage + career health + overall summary. Stored as JSON in the
# fighter_descriptors table (Task 19).
# ----------------------------------------------------------------

def build_descriptor_snapshot(attrs, pers, fighter_data, rng=None):
    """Build a complete descriptor snapshot for a fighter.

    Args:
        attrs: dict of {attr_name: value} for all 25 attributes.
        pers: dict of {trait_name: value} for all 20 personality traits.
        fighter_data: dict with career state (age, record, champion,
            streaks, health, style_archetype_name, etc.).
        rng: optional random.Random.

    Returns:
        A dict with keys:
            - attribute_descriptors: {attr_name: descriptor_str}
            - personality_descriptors: {trait_name: descriptor_str}
            - career_stage: str
            - career_health: str
            - potential_descriptor: str or None (None if not scouted)
            - overall: str (one-sentence summary)
    """
    attr_descs = {}
    for attr_name, value in attrs.items():
        attr_descs[attr_name] = describe_attribute(attr_name, value, rng)
    pers_descs = {}
    for trait_name, value in pers.items():
        pers_descs[trait_name] = describe_personality(trait_name, value, rng)
    career_stage = describe_career_stage(
        fighter_data.get("age", 30),
        fighter_data.get("record_wins", 0),
        fighter_data.get("record_losses", 0),
        fighter_data.get("record_draws", 0),
        fighter_data.get("is_champion", False),
        fighter_data.get("title_reigns", 0),
        fighter_data.get("win_streak", 0),
        fighter_data.get("loss_streak", 0),
        rng,
    )
    career_health = describe_career_health(
        fighter_data.get("career_health", 100), rng
    )
    # Potential: NOT included in the snapshot by default (hidden).
    # The scouting system (Task 18) will request it separately with
    # scouted=True.
    potential_desc = None
    # Overall summary
    # Pick top 3 attributes by value for the summary flavor
    sorted_attrs = sorted(attrs.items(), key=lambda x: x[1], reverse=True)
    fighter_data["key_attributes"] = dict(sorted_attrs[:3])
    overall = describe_overall(fighter_data, rng)
    return {
        "attribute_descriptors": attr_descs,
        "personality_descriptors": pers_descs,
        "career_stage": career_stage,
        "career_health": career_health,
        "potential_descriptor": potential_desc,
        "overall": overall,
    }
