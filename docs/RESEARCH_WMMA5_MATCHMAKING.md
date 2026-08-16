> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# Research: WMMA5 Matchmaking + Event Building

**Task ID:** RESEARCH-WMMA5-MATCHMAKING
**Scope:** Web research + analysis of *World of Mixed Martial Arts 5* (Grey Dog
Software, 2018, designer Adam Ryland) — its matchmaking UX, event-building flow,
show-quality model, and AI booking — for the express purpose of informing
CAGE EMPIRE's matchmaking screen. **No code changes.**

---

## Sources Consulted

| Source | URL | What it gave us |
|---|---|---|
| WMMA5 Player's Handbook (community-maintained, 125KB) | hansmellman.github.io/wmma5-players-handbook | Definitive mechanics: Commercial Rating, Critical Rating, Attendance Levels, Match Making philosophy, Hype, Inducements, Challenges, Post-Event Effects |
| WMMA5 Developer's Journal (175 entries, Adam Ryland, Oct–Nov 2017) | forum.greydogsoftware.com/topic/44306-wmma5-developers-journal | Every new feature added in WMMA5 over WMMA4, including #22 Quick Move Fight, #42 Booking Adviser, #50 Combatative AI, #77 Fighter Heat, #100 Tagging, #146 Likely Usage, #147 Fight Rating Display, #152 Short Notice Search, #160 Replacement Offers, #170 Match Making Enhanced Sorting |
| Steam Community Guide: "Booking an event" (Marginal0, 2015) | steamcommunity.com/sharedfiles/filedetails/?id=413446310 | Step-by-step first-event booking walkthrough — confirms the exact UI flow (two-column layout, Search/Compare/Fan Feedback/Hype/Add buttons, card-order arrows) |
| Grey Dog Forum: "How do I book a Match Card?" (Feb 2020, 2 pages, includes reply from designer Adam Ryland) | forum.greydogsoftware.com/topic/47293-how-do-i-book-a-match-card | Confirms card-order rules (main event strongest, co-main 2nd), the rankings-vs-popularity distinction, the "name value" guide for card placement |
| Grey Dog Forum: "Booking schemes and philosophy" (Jan 2018, 2 pages) | forum.greydogsoftware.com/topic/44531-booking-schemes-and-philosophy | How veteran players actually book: momentum matching, "pyramid booking", cherry-picking opponents to build stars, planning 3 title fights ahead |
| Reddit r/WMMA5: "Tips for booking and getting popular" | reddit.com/r/WMMA5/comments/esjryw | "Two +5 momentum fighters fighting will pull a much higher rating than their popularity dictates" — momentum matters |
| Reddit r/WMMA5: "Matchmaking Tips" | reddit.com/r/WMMA5/comments/oos9s1 | "Click the Compare button, make sure the fighters skillsets are evenly matched or balanced" |
| Reddit r/WMMA5: "Automatic Matchmaking?" | reddit.com/r/WMMA5/comments/1ccvq6q | Confirms **no AI auto-book for the player** — community opinion: "Matchmaking is the most enjoyable aspect of the game, why let an AI do it" |
| Reddit r/WMMA5: "Few Questions from a Beginner" | reddit.com/r/WMMA5/comments/1bbxgp8 | Card sizes: "9 fights per card, 4 prelims + 5 main card… 8 minimum to not gather any penalty" |
| Reddit r/WMMA5: "Broadcasting Strategies" + "Creating your own broadcaster" | reddit.com/r/WMMA5/comments/12k19ax, /n1oz2m | Broadcasting layers: PPV vs TV vs Streaming, reach tiers, "PPV makes about $31-33M usually" |
| Fuldapocalypse Fiction: "WMMA5 Style Archetypes" | fuldapocalypsefiction.com/2022/04/09/wmma5-style-archetypes | Style archetype diversity the engine supports (sumo, shootfighting, brawler, points fighter, hillbilly) |

*(Reddit pages were partially blocked by their bot wall — snippets from search
results used where the live page was inaccessible. Handbook + dev journal +
forum threads provided the bulk of the authoritative content.)*

---

## 1. WMMA5 Matchmaking UX

### 1.1 The Match Making screen — what it actually looks like

The Match Making screen is reached from **Your Office → Match Making** (or the
customisable info-bar shortcut, dev-journal #107). Its layout (confirmed by
the Steam community guide and the dev journal):

```
┌──────────────────────────────────────────────────────────────────┐
│  Weight Class: [▼ Featherweight]   Event: [XCC: Ziskie vs Nunes] │
│  Title on the line: [▼ None ▼]                                   │
├─────────────────────────────┬────────────────────────────────────┤
│   BLUE CORNER               │   RED CORNER                       │
│   ┌──────────┐              │              ┌──────────┐          │
│   │ fighter  │   [Compare]  │   [Fan       │ fighter  │          │
│   │ portrait │   ◄─────────►│   Feedback]  │ portrait │          │
│   └──────────┘              │              └──────────┘          │
│   Name / Record / Rank      │   Name / Record / Rank             │
│   Name Value: Mid Regional  │   Name Value: Low Regional         │
│   [Search] [Rankings]       │   [Search] [Rankings]              │
│   [Titles]  [View Profile]  │   [Titles]  [View Profile]        │
│   [Scout]                   │   [Scout]                          │
├─────────────────────────────┴────────────────────────────────────┤
│  Hype slider: [None | Small | Medium | Large (fighter #1|#2)]    │
│  Inducements icons: [training time] [opponent] [weight class]    │
│  [Add Match to Card]  [Reset Search]                             │
├──────────────────────────────────────────────────────────────────┤
│  CURRENT CARD                                                   │
│  1. (Main Event)      Ziskie (c) vs Nunes      [▲][▼] [×]       │
│     Side panel: DRAW ★★★★☆  Heat: 0   Inducements: —            │
│  2. (Co-Main)         Milissis vs Magilton     [▲][▼] [×]       │
│     Side panel: DRAW ★★★☆☆  Heat: 0   Inducements: $5k         │
│  3. (Main Card)       Watson vs King           [▲][▼] [×]       │
│     Side panel: DRAW ★★☆☆☆  Heat: 0   Inducements: —            │
│  ...                                                            │
│  7. (Prelim)          ...                                       │
│                                                                 │
│  [Booking Adviser] [Absences] [Quick Move Fight]                │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 How a matchup is built (step by step, from the Steam guide)

1. **Set the weight class** at the top-left dropdown (or "No Division" for
   open-weight).
2. **Find the first fighter** — either scroll the roster list, or hit
   **Search** to open a filter popup (Min. Name Value, Pro Record, Weight
   Class, Status). Click a fighter in the blue column.
3. **Check their ranking** — **Rankings** button below the selected fighter
   opens the world/company rankings with a hover tooltip showing each
   fighter's rank. Pick the opponent from the rankings list.
4. **Check available titles** — **Titles** button shows current champions
   per weight class. To put a title on the line, set the "Title on the line"
   dropdown at the top BEFORE clicking Add.
5. **Click the second fighter** in the red column.
6. **Press Compare** — opens a side-by-side analysis screen showing the
   style matchup (e.g., *"classic striker vs grappler matchup, with
   Milissis' wrestling matching up to that of Magilton's. He should win if
   he avoids being taken down, though lack of experience might doom him."*).
   This is **text-based**, not a visual radar chart.
7. **Press Fan Feedback** — the game returns a one-line reaction
   (e.g., *"fans think this is a worthy main event"*) telling you whether
   the matchup is a credible headline fight for your company's size.
8. **(Optional) Set Hype slider** — None / Small / Medium / Large — to
   push marketing weight behind one fighter. Raises potential popularity
   gain if they win, magnifies losses if they lose.
9. **Press Add** — the matchup lands on the card.
10. **Press Add Match** to book the next fight; repeat.
11. **Reorder the card** with the ▲/▼ arrows on the right of each fight
    row. Moving a fight below a certain point makes it a **Preliminary**
    bout (visually demarcated).

### 1.3 What information is shown when selecting fighters

Per fighter (visible in the side panel without leaving the screen):

| Field | Where it comes from |
|---|---|
| Portrait + name + nickname | `fighters` table |
| Pro record (W-L-D) | career fight history |
| Company rank + world rank | `rankings` |
| **Name Value** (popularity tier) | `fighters.popularity` — text label like "Mid Level Regional", "Low Level National", "Cult Hero", "Household Name" |
| Style archetype | "Striker", "Grappler", "Wrestler", "Balanced", etc |
| Weight class | `weight_classes` |
| Next fight / Last fight | dev-journal #110: defaults to last fight if nothing scheduled |
| **Likely Usage** (text approximation of worth) | dev-journal #146 — *"gives the user an instant approximation of a fighter's popularity and worth to the company"* |
| **Momentum / Fighter Heat** | dev-journal #77 — flame icons, overhauled to factor in type/speed of victory, betting lines, world ranking |
| **Inducements** (icons next to the fight) | training-time, opponent-specific, difficulty, weight-class |
| **Personality + Persona** | dev-journal #149 — both visible in profile |
| **Popularity change arrows** | dev-journal #108/#109 — visible after each event |

### 1.4 Tale of the tape?

**No, not really.** The **Compare** button opens a side-by-side screen, but
it is **text-based**: a paragraph of natural-language analysis
(*"striker vs grappler matchup, X's wrestling matches up to Y's, he should
win if he avoids being taken down"*). There is **no visual radar chart**,
**no stat-by-stat bar comparison**, **no reach/height/age comparison
graphic**. This is one of WMMA5's clearest UX weaknesses — and an obvious
place for CAGE EMPIRE to improve.

### 1.5 Style matchup analysis?

**Yes, but as natural-language text** generated from the fighters' skill
profiles (compare-button output: *"classic striker vs grappler matchup"*).
The engine does support nuanced style archetypes — the Fuldapocalypse blog
catalogues 6+ exotic ones (sumo, shootfighting, "practical fighters",
brawlers, points fighters, hillbilly fighters). The 25-attribute skill
system (Standing, Ground, Wrestling, Muay Thai, Mental, General sub-trees)
is deep — but the matchmaking screen doesn't *visualise* it.

### 1.6 Ranking gap / ranking implications?

**Rankings are visible** (Rankings button below each selected fighter, with
hover tooltips), and the **Fan Feedback** button implicitly tells you
whether a fight "makes sense" for your company's size. But:

- There is **no explicit "ranking implications" prediction** (e.g., *"if #7
  wins, they move to #3; if they lose, they drop to #11"*).
- There is **no "winner fights for the title next" indicator** — the player
  has to mentally keep track of the contender ladder.
- The handbook is explicit that **rankings ≠ popularity**: *"rankings are
  about how good a fighter is, the guide to where to put them on the card
  is about how popular they are. They're explicitly measures of two totally
  different aspects."* (Adam Ryland, forum reply, Feb 2020.)

### 1.7 Predicted fight quality / fan interest?

**Partially.** The two relevant signals:

- **Fan Feedback** (per-fight button) — one-line reaction. Tells you
  whether the fight is "a worthy main event" / "decent co-main" / "prelim
  level". This is **per-fight**, not per-card.
- **Side-panel DRAW stars** on each booked fight — a 0–5 star
  representation of the fight's draw (commercial attractiveness). The
  handbook: *"You can see this via the side panels on the match making
  screen(s)."*

But there is **no aggregated "card quality score"** during the build, and
**no live attendance / buyrate projection** while you book. You see the
Commercial Rating + Critical Rating only **after** the event happens.

### 1.8 Weight classes

- A weight-class dropdown at the top of the screen filters the roster.
- Fighters can be booked at their natural weight class OR moved up/down
  (dev-journal #167: Weight Class Movement feature).
- "No Division" option exists for open-weight / catchweight bouts.
- Weight-class inducements: a fighter asked to fight outside their natural
  class may demand extra money (dev-journal #130: Inducements And
  Personalities).
- Weight cutting is simulated (dev-journal #93–98: Adjusted Weight
  Cutting, Weight Data Check, Target Weights, Mass Edit Auto Weights,
  Generated Weight Settings, Weight Cutting Levels). Bad cuts can apply
  pre-fight skill penalties (handbook: Skill Changes Pre-Fight).

### 1.9 Fighter availability (injured / suspended / already booked)?

- **Absences button** on the match making screen (dev-journal #144) lists
  every currently-unavailable fighter in one place — *"makes match making
  easier and has been requested a lot."*
- Injured and suspended fighters are filtered out of the selectable roster
  automatically.
- **Already-booked fighters** simply don't appear in the picker for the
  date range of the event you're booking.
- **Replacement Offers** (dev-journal #160): if a fighter withdraws from a
  booked fight due to injury, other fighters can privately email the
  player offering themselves as a short-notice replacement — and will
  almost never turn the fight down if offered within 7 days.
- **Short Notice Search** (dev-journal #152): a search filter for fighters
  willing to take a short-notice booking.

---

## 2. Event Building Flow

### 2.1 How does the player create an event?

From the Match Making screen:

1. **Match Making button** (Your Office, or custom info-bar).
2. **Add an Event** — opens a popup to name the event + pick a date.
3. **Minimum lead time**: 1 month (handbook: *"You must give at least one
   month's time for the show to be organised, except in the first week of
   the game when you only require two weeks of preparation time."*).
4. **No limit on simultaneously-scheduled shows** — you can have several
   events booked at once.
5. Booking **>1 month out** has trade-offs (handbook):
   - **Pro**: lets you grab shared (non-exclusive) fighters before rivals
     do; lets fighters build heat/hype over a longer lead.
   - **Con**: longer training camps = higher injury risk.

### 2.2 Venue / region selection — how does it work?

- When scheduling an event the player picks a **game region** (e.g.,
  Tri-State, Texas, South East England, Kanto). Each region has fixed
  properties (handbook: *"All regions have settings for their size,
  political bias, lucrative rating, etc. These can be seen via the game
  world screen, when choosing a location to hold a show, and in the
  editor."*)
- The handbook implies **specific venue selection is minimal** — the
  region's properties drive attendance, not a per-venue capacity picker.
  (This is one of WMMA5's limitations — and one of CAGE EMPIRE's
  advantages: we have a `venues` table with capacity, rental cost, venue
  type.)
- **Attendance is region-driven**: *"a base number is created by looking
  at the popularity of the company in the game area in which the show is
  being held. This can go from 80 to 50,000."* Then adjusted by:
  1. Commercial Rating of the show
  2. Momentum of the company
  3. How long since the company last featured legit star names
  4. Economy in that area
  5. Marketing level applied to the show
  6. Company Credibility
- **Ticket pricing is automatic** — *"calculated primarily from the size
  of the company, with further modifications based upon the size and
  lucrative rating of the region."* **The player has no direct control
  over ticket price.** (Handbook: *"Ticket pricing is handled
  automatically and cannot be impacted by the player."*)

> ⚠️ **CAGE EMPIRE already beats WMMA5 here** — our event builder has an
> explicit venue picker (capacity / rental / venue type) + ticket-price
> + marketing + PPV-price levers. WMMA5 has none of that player control.

### 2.3 How are fights added to the card?

- **Select-from-list, not drag-drop.** Pick fighter A in the blue column,
  fighter B in the red column, click Add. Repeat.
- **Quick Move Fight** (dev-journal #22): a button to move a booked fight
  from one event to another without cancelling and re-booking — *"avoids
  needing to cancel and re-book each time. The process automatically
  takes into account existing training times and whether the fighters
  are willing to make the move."*
- **No auto-suggest.** The Booking Adviser (next section) surfaces
  *opportunities* but doesn't auto-suggest specific fights. The player
  has to pick both fighters manually.
- **No drag-drop reordering** — ▲▼ arrow buttons per row.

### 2.4 Card order (main event / co-main / prelims)?

Yes, explicit. From the handbook and forum:

- **Main event** = the strongest drawing fight.
- **Co-main event** = the 2nd strongest drawing fight.
- **Main show / main card** = the rest of the televised fights.
- **Prelims** = fights below the line.
- The handbook: *"With the main and co-main event, you are primarily
  looking at the 'draw' of the fight. With the remainder of the fights,
  the 'draw' is less important as it has far less impact on the success
  of the show (particularly the prelims, where the 'draw' is irrelevant)."*
- Moving a fight down the card past a threshold marks it as Preliminary.
- The Commercial Rating is calculated primarily from **main event +
  co-main event draw** — main event is by far the most important. If
  co-main is a bigger draw than main event, they're effectively swapped
  for the calculation. *"A strong main show undercard can give a mild
  boost to the final rating, while the preliminary fights have no impact
  at all."*
- Card-order penalties: there's a soft penalty for mismatched card
  placement — the game's "card placement guide" tells you when a fighter
  is "prelim level" / "main card level" / "main event level" based on
  their **popularity vs company size**, not their ranking.

### 2.5 How many fights per card typically?

Community consensus (Reddit / forum threads):

- **Minimum: 8 fights** to avoid a penalty (one commenter: *"you get
  penalties if you have less than 8 matches"*).
- **Typical: 9–12 fights** = 4–5 prelims + 5–6 main card.
- Some players run 6 main card + 9 prelims (15 total) when they have a
  bloated roster.
- WMMA5 enforces no hard cap — just payroll pressure (more fights = more
  fighter payouts).

### 2.6 Does it show projected attendance / buyrate / revenue as you build?

**No.** This is one of WMMA5's biggest gaps. The Match Making screen shows:

- Per-fight DRAW stars (★ rating) on the side panel.
- Per-fight **Fan Feedback** (one-line reaction).
- **Inducements icons** (extra costs you'll pay).

But it does **NOT** show:

- Projected attendance.
- Projected PPV buys.
- Projected gate / revenue / net profit.
- A combined "card quality score".
- A projected Commercial/Critical Rating before the event happens.

The player has to *intuit* card quality from the per-fight stars + fan
feedback, and then experience the actual numbers after the event. **This
is exactly the gap CAGE EMPIRE is closing** (per
`docs/RESEARCH_MATCHMAKING_SHOWRATING.md`: the `card_draw = 1.2`
hardcoded preview multiplier).

### 2.7 Does card quality affect the projection?

In WMMA5's case the question is moot (no projection exists). But card
quality **does** drive the *post-event* Commercial Rating, which drives:

- Attendance (next time — the company's popularity grows or shrinks).
- PPV buyrate / broadcast revenue.
- Future fighter popularity gains (fighters on a high-rated card gain
  more popularity).
- Company momentum (which feeds the next event's attendance).

So the feedback loop is **one event delayed**: card quality → event
rating → popularity change → next event's attendance.

---

## 3. Show Quality / Rating

### 3.1 Does WMMA5 rate shows after they happen?

**Yes — and it uses TWO separate ratings, not one.** This is a critical
design choice we should learn from.

| Rating | Measures | Calculation |
|---|---|---|
| **Commercial Rating** | "Draw" — how attractive the card was on paper | Primarily **main event draw + co-main event draw** (main event dominant; if co-main > main event, they swap). Strong undercard = mild boost. **Prelims have ZERO impact.** |
| **Critical Rating** | How exciting the event actually was | **3 highest-rated fights on the main show** (prelims excluded). Bonus if main event was one of the best 2 fights. **Boring fights do NOT lower the rating** — as long as the show has 3 good fights, it does fine. |

The handbook: *"The impact of a show on a company's popularity is
primarily based on the Commercial Rating and Critical Rating, although
the type and level of broadcasting (if any) can affect the size of the
change and there are also potential penalties for things like poor
quality announcing."*

### 3.2 What factors affect the rating?

**Commercial Rating inputs:**
- Main event draw (fighter popularity × title-fight bonus × rivalry heat)
- Co-main event draw
- Mild boost from a strong main-card undercard
- Penalties from **Event Disruption** (up to −15% for a severely
  disrupted show; main-event injuries hurt more than prelim changes)
- Broadcasting type/level modifiers

**Critical Rating inputs:**
- Fight rating of the top 3 main-show fights (computed from a hidden
  points system — strikes, takedowns, sweeps, passes = positive points;
  grappling stalemates, wall-and-stall, inactivity = negative points)
- **Finishes** add positive points (decisions are effectively punished
  because they get no finish bonus)
- Bonus if main event was one of the best 2 fights on the show

**Fight Rating** (per-fight, feeds Critical Rating):
- Every exciting event (strike landing, takedown, sweep, pass) gets +points
- Every dull event (grappling stalemate, wall-and-stall, inactivity) gets
  −points
- A fight that goes to decision is "in effect punished because it will
  not be receiving the positive points that an actual finish would have
  provided"
- Final tally = the fight's rating, which is "a direct measure of how
  exciting it was for the fans"

### 3.3 Does it project show quality BEFORE the event?

**Only weakly.** WMMA5 has:

- **Per-fight Fan Feedback** during booking (one-line reaction).
- **Pre-show commentary/analysis** when the player advances to the event
  (the commentators give a pre-fight breakdown — handbook shortcut keys
  mention "reading pre-show previews").
- The **side-panel DRAW stars** per booked fight.

But there is **no aggregated pre-event "projected Commercial Rating"**,
no projected attendance, no projected buyrate. The player books on
instinct + per-fight feedback, then sees what happens.

> ⚠️ **CAGE EMPIRE opportunity**: we already have a 5-axis show-rating
> engine (`src/show_rating.py`) that runs post-event. Two of those axes
> (`commercial_rating`, `quality_rating`) are **100% projectable
> pre-event** because they only use known quantities (fighter
> marketability, broadcast tier, fighter attributes, fight IQ). This is
> documented in our `docs/RESEARCH_MATCHMAKING_SHOWRATING.md` §"Can it
> be used for PRE-event projection?". We should build a **pre-event
> projection** that mirrors WMMA5's two-rating split.

### 3.4 How does show quality affect revenue?

The chain (handbook: Post-Event Effects):

```
show quality (commercial + critical)
   ↓
company popularity change (per game area where held/broadcast)
   ↓
next event's base attendance (80 → 50,000 range, popularity-driven)
   ↓
gate receipt = attendance × avg ticket price
   ↓
plus broadcast revenue (PPV / TV / streaming)
   ↓
minus fighter payroll + venue rental + marketing + staff
   ↓
net profit / loss
```

Key levers:
- **Commercial Rating** is the dominant factor in popularity change.
- **Critical Rating** is "sizeable but definitely secondary".
- **Broadcasting type** can amplify or dampen the popularity swing.
- A separate Commercial Rating is calculated **per game area** where the
  show was held or broadcast — so a PPV broadcast internationally moves
  the popularity needle in every market it touches.
- **Poor quality announcing** (a staff issue) applies a penalty.

---

## 4. AI Matchmaking

### 4.1 Does the AI auto-book fights for rival promotions?

**Yes.** AI-controlled companies book their own cards, sign their own
fighters, run their own title pictures. The handbook: *"AI-controlled
companies will only ever use one night tournaments if they have been
pre-set to via the Grand Prix section of the editor"* — implying the AI
runs the full event lifecycle autonomously.

The AI also books its annual grand prix one month ahead (e.g., a July
grand prix is booked in June). The AI *"cannot 'back track' to make up
bookings"* — if the game starts in January and the AI's grand prix is
set for January, it skips that year.

### 4.2 Does the AI suggest matchups for the player?

**Yes — via the Booking Adviser** (dev-journal #42):

> *"A booking adviser has been added to the game to make life easier for
> the match maker. This has a number of tabs that can be activated that
> list things like your current hometown fighters, potential champion
> vs #1 contender fights that can be made, fighters who you have yet to
> debut, etc, etc. This helps you keep track of things and avoid
> forgetting to do things."*

So the Booking Adviser is a **filter/surfacing tool**, not an
auto-booker. It surfaces *opportunities* (hometown fighters in this
region, debuting fighters, #1-contender fights that can be made) — but
the player still picks the matchup. Other relevant AI-assist features:

- **Match Making Enhanced Sorting** (dev-journal #170): improved
  roster-list sorting on the match making screen.
- **Potential Hirings** (dev-journal #78): a screen "based on TEW's
  Creative Meeting" — recommends free agents to sign, with filters.
- **Attribute Suggestions** (dev-journal #157): suggests attribute
  values during fighter creation/editing.
- **Quick Move Fight** (dev-journal #22): moves a fight between events
  automatically (handles training-time + willingness checks).

### 4.3 Is there a "matchmaker" staff role that affects booking quality?

**No dedicated matchmaker staff role** — the player IS the matchmaker
(as CEO/Owner avatar). However, there are staff roles that affect
related systems:

- **Commentators** — affect broadcast quality (poor announcing = penalty
  to popularity change).
- **Scouts** — affect how much you can see about a fighter's true
  attributes (dev-journals #83–85: Scouting Upgrade, Scout From Profile,
  Scouting Costs).
- **Trainers / Teams** — affect fighter skill development between fights.
- **Drug testing agencies** (dev-journal #79): named bodies with
  quality/reputation settings.

So staff affect the *context* around matchmaking (what you can see,
how fighters develop, broadcast quality) but **no staff member
"bookes better fights"**. Booking quality is purely the player's skill.

### 4.4 Combatative AI (rival promotions)

Dev-journal #50: *"Taken from TEW2016, WMMA5 features a similar
'combatative AI' in that AI-controlled companies now have the ability
to understand and respond to other company's fighter offers. This
allows them to be more combatative and less passive, actively trying to
disrupt opponents and fight for the best talent."*

So rival promotions will:
- Out-bid you for free agents you're pursuing.
- Try to poach your exclusive fighters during renegotiation windows.
- Grab shared (non-exclusive) fighters before you do if you book far
  ahead.

---

## 5. What WMMA5 Does Well

### 5.1 Two-column "blue corner vs red corner" layout
The visual metaphor is *instantly readable* — every MMA fan understands
blue vs red corner. Selecting fighter A on the left, fighter B on the
right, and hitting Add is a 3-click matchup. No modal confusion. This
is the "easy" the user mentioned.

### 5.2 The Compare button (style matchup analysis)
Even though it's text-only, the Compare button generates *meaningful*
natural-language analysis of how two fighters' styles match up
(*"striker vs grappler, X's wrestling matches Y's, he should win if he
avoids being taken down"*). It's the engine *explaining itself* to the
player, which builds trust and teaches the game's logic.

### 5.3 The Fan Feedback button
One click → one line of feedback (*"fans think this is a worthy main
event"*). This is a *brilliant* UX move: it tells the player whether
their matchup is credible for their company's size, in the game's own
voice, without showing raw numbers. CAGE EMPIRE's voice layer is
perfectly suited to this.

### 5.4 Side-panel DRAW stars per fight
A 0–5 star visual on each booked fight gives at-a-glance card-quality
feedback during the build. Combined with the main-event-dominates
calculation rule, the player can quickly see whether their main event
is strong enough.

### 5.5 Booking Adviser (opportunity surfacing)
Tabs that surface *opportunities* the player might forget: hometown
fighters for a regional show, #1-contender fights that can be made,
fighters yet to debut. This is the right balance of AI assistance
without AI auto-booking — it *augments* the player's judgement rather
than replacing it. (Reddit's "Automatic Matchmaking?" thread confirms
the community would *reject* full auto-booking: *"Matchmaking is the
most enjoyable aspect of the game, why let an AI do it."*)

### 5.6 Two-rating split (Commercial vs Critical)
This is **the most important design insight in the whole research**.
Splitting "how attractive was the card on paper" (Commercial) from
"how exciting was it actually" (Critical) creates **two distinct
strategies**:

- A *commercial promoter* books big-name fights that may stink (a
  38-year-old legend vs a popular YouTuber).
- A *critical purist* books stylistically fascinating fights between
  unknowns (two grapplers with submission specialist attributes).
- Both can be valid play styles, and the game rewards each
  differently.

CAGE EMPIRE's 5-axis rating (fan / commercial / excitement / quality /
overall) is *more* granular than WMMA5's 2-axis split — but we should
make sure the *distinction* between "card on paper" and "card as it
played out" is preserved.

### 5.7 Momentum / Fighter Heat (flame icons)
Dev-journal #77 overhauled the flame-icon system to factor in
type/speed of victory, betting lines, world ranking. Reddit confirms:
*"Two +5 momentum fighters fighting will pull a much higher rating
than their popularity dictates. Momentum is super important."* This is
a *non-obvious* lever the player can exploit (build win streaks, then
cash them in against each other) — exactly the kind of strategic
depth CAGE EMPIRE's "rewarding, not easy mode" goal calls for.

### 5.8 Hype slider (risk/reward on individual fighters)
Player can manually push marketing weight behind one fighter
(None/Small/Medium/Large). If they win, bigger popularity gain. If
they lose, magnified popularity loss. This is a **player-authored
risk lever** that creates storylines — *"I hyped Watson to the moon
and she got knocked out in 14 seconds"* — which is exactly the kind
of memory CAGE EMPIRE's Soul document says we should optimize for.

### 5.9 Quick Move Fight (move fight between events)
A single button moves a booked fight to another event, automatically
handling training-time recalculation and willingness checks. Saves
the cancel-and-rebook friction that makes WMMA5's rivals tedious.

### 5.10 Replacement Offers (organic short-notice fill-ins)
When a fighter withdraws, other fighters *privately email* the player
offering to step in. The offering fighter is *"extremely unlikely to
turn down the fight if offered within seven days"*. This is organic,
narrative-rich, and avoids the player having to scramble through the
roster manually.

### 5.11 Pre-show commentary / analysis
When the player advances to an event, commentators give a pre-fight
breakdown. Shortcut keys (space/backspace/enter/s/b/t) let the player
read it at their own pace. This builds anticipation — the gap between
booking and watching is filled with narrative texture.

### 5.12 Distinct "rankings" vs "popularity" signals
The handbook is explicit that these are *separate* measures. A #1
ranked fighter with low popularity is a *problem to solve* (build
their profile), not a bug. This creates the strategic depth of "good
vs popular" that mirrors real MMA (Demetrious Johnson was the GOAT
flyweight but a poor PPV draw).

---

## 6. What WMMA5 Does Poorly

### 6.1 DATED, spreadsheet-like UI
WMMA5 is a Windows desktop app from 2018 built on a 2000s-era UI
toolkit. The interface is functional but visually flat: tables, dropdowns,
grey panels. The Steam guide and forum threads are full of new players
asking *"how do I book a card?"* — a sign the UI doesn't communicate
its own workflow. **CAGE EMPIRE's web-based UI already has a visual
advantage** (cards, gradients, portraits, venue icons).

### 6.2 The "prelim level" advice is confusing
Veteran players explicitly tell newcomers to *"ignore the game any time
it tells you a fight should be on the prelims"* (forum: BrokenCycle,
Feb 2020). The game communicates *that* a fighter is "prelim level"
but not *why*, leading to frustration. The designer (Adam Ryland) had
to step into the thread to clarify: rankings = skill, name value =
draw. **The distinction is correct; the communication is broken.**

### 6.3 No live attendance / buyrate / revenue projection during the build
**This is WMMA5's single biggest UX gap — and the one CAGE EMPIRE is
specifically trying to close.** The Match Making screen shows per-fight
stars and fan feedback, but no aggregated projection. The player books
blind, then learns whether the card was commercially viable only after
the event resolves. **CAGE EMPIRE's `event_builder.js` already has the
venue + levers + live P&L preview scaffolding — we just need to feed
real card-quality into it.**

### 6.4 Compare button is text-only (no visual radar / tale-of-tape graphic)
The Compare button outputs a paragraph of natural-language analysis.
There is **no visual radar chart**, **no side-by-side stat bars**,
**no reach/height/age comparison graphic**. For a game with 25+
attributes per fighter, this is a missed opportunity. Modern sports
games (EA UFC, OOTP) all use visual stat comparisons.

### 6.5 No "ranking implications" prediction
The player can see current rankings, but the game doesn't predict
*"if #7 wins they move to #3; if they lose they drop to #11"* — even
though the engine obviously knows this. The player has to mentally
maintain the contender ladder. **This is a place CAGE EMPIRE can
add real value** with a simple "what this fight means for the
rankings" preview.

### 6.6 Prelims have ZERO impact on the rating
Handbook: *"the preliminary fights have no impact at all"* on the
Commercial Rating, and prelims are excluded from the Critical Rating's
top-3-fights calculation. This means **building prelims feels
pointless** — they don't move the needle. Players still book them for
realism, but the game gives them no reward. **CAGE EMPIRE could
improve by giving prelims a small but nonzero commercial contribution**
(e.g., a "depth of card" bonus, or a "fan experience" sub-axis).

### 6.7 No drag-and-drop card reordering
Card order is set with ▲▼ arrow buttons. Functional, but slow for
rearranging a 10-fight card. Modern web UIs make drag-drop trivial.

### 6.8 No smart matchup suggestions
The Booking Adviser surfaces *opportunities* (hometown fighters,
debuts, #1-contender fights) but doesn't suggest *specific matchups*.
There's no *"Book Fighter A vs Fighter B — both are on 3-fight win
streaks in the same division"* suggestion engine. The player has to
do all the creative work themselves.

### 6.9 No "card coherence" feedback
WMMA5 doesn't tell the player *"your card has 4 strikers and 0
grapplers — fans might find this repetitive"* or *"you've booked 3
fights in the same weight class — consider spreading out"*. The
booking is per-fight, not holistic.

### 6.10 Ticket pricing is automatic (no player control)
The handbook is explicit: *"Ticket pricing is handled automatically
and cannot be impacted by the player."* This removes a meaningful
financial lever. **CAGE EMPIRE already gives the player a ticket-price
slider** in `event_builder.js` — a clear improvement.

### 6.11 No pre-event "card quality score"
Despite having all the data needed (main event marketability, co-main
marketability, title fights, rivalry heat — see `finance.py::
_compute_broadcast_revenue`'s `card_draw_multiplier`), WMMA5 doesn't
surface a pre-event projection of the Commercial Rating. The player
has to wait until after the event. **CAGE EMPIRE's finance engine
already computes this — we just need to expose it during the build.**

### 6.12 Critical Rating doesn't explain itself
Post-event, the player sees a Critical Rating (e.g., "Decent", "Great")
but not *why*. Was it the main event? The 3 top fights? A specific
finishing sequence? The handbook explains the formula but the game
doesn't surface it. **CAGE EMPIRE's interpretation layer is built for
exactly this** — translating raw numbers into player-readable
"why did this card rate 73/100?" explanations.

### 6.13 Card-placement advice is one-dimensional
The "name value" guide tells you whether a fighter is main-event /
main-card / prelim level — but it doesn't factor in *opponent*. A
mid-tier fighter against a star might be a credible co-main; the same
fighter against another mid-tier fighter is a prelim. WMMA5's advice
is per-fighter, not per-matchup.

### 6.14 Information overload across many screens
The handbook is 125KB of mechanics. New players face: Match Making
screen, Booking Adviser, Absences, Rankings, Titles, Search, Scout,
Hype, Inducements, Replacement Offers, Quick Hire, Talk To Fighter,
etc. Each is a separate screen with its own buttons. **CAGE EMPIRE
should consolidate** — fewer screens, more inline context.

### 6.15 No "tale of the tape" graphic
Despite being an iconic MMA broadcast element, WMMA5 has no visual
tale-of-the-tape comparison (height, reach, age, record, style). The
Compare button is text-only. This is a missed opportunity for both
immersion and quick readability.

---

## 7. Recommendations for CAGE EMPIRE

The user said: *"research how WMMA5 (grey dog) does this because it works
well and is easy but we are improving it vastly."* WMMA5's "easy" comes
from: 2-column layout, Compare button, Fan Feedback, side-panel stars.
WMMA5's "works well" comes from: 2-rating split, momentum/heat,Booking
Adviser. The "improving it vastly" opportunity is: live projection,
visual tale-of-tape, ranking implications, smart suggestions, voice-layer
explanations.

### 7.1 What to LEARN from WMMA5 (copy these patterns)

| WMMA5 pattern | CAGE EMPIRE implementation |
|---|---|
| **2-column blue/red corner layout** | Our matchmaking screen (`src/web/js/matchmaking.js` — to be created) should default to a 2-column "RED CORNER / BLUE CORNER" layout. Fighter portrait + name + record + rank + marketability chip in each column. Click a fighter in the roster list → they populate the next available corner slot. |
| **Compare button (style matchup analysis)** | Add a "Compare" button below the two selected fighters that opens a visual radar chart + natural-language analysis. The NL analysis should come from our voice layer (e.g., *"Reed's boxing vs Vale's wrestling — if Reed can keep it standing, he's got the chin to weather the early storm"*). |
| **Fan Feedback button** | Add a "Fan Pulse" or "Buzz" button that returns one line of voice-layer feedback on the proposed matchup (*"Fans are buzzing — this is the fight they've been asking for"* / *"Crickets. Nobody knows who these two are"*). Should factor in: fighter marketability, ranking gap, rivalry heat, momentum, title implications. |
| **Side-panel DRAW stars per fight** | Each booked fight on the card shows a 0–5 star "Draw" rating computed from the same formula as `finance.py::_compute_broadcast_revenue`'s `card_draw_multiplier`. Updates live as the player adds/reorders fights. |
| **Booking Adviser (opportunity surfacing)** | A collapsible side panel with tabs: "Hometown Fighters" (for the selected venue's region), "Win Streaks" (fighters on 3+ fight win streaks who haven't fought each other), "Debuts" (signed fighters with 0 fights for your promo), "Title Picture" (champion + top 5 contenders per weight class + who's available). NO auto-book — just surfacing. |
| **2-rating split (Commercial vs Critical)** | Our `show_rating.py` already has 5 axes (fan / commercial / excitement / quality / overall). For the **pre-event projection**, surface 2 numbers: "Projected Draw" (= commercial axis, projectable) and "Card Quality" (= quality axis, projectable). Leave fan/excitement/overall as post-event only. |
| **Momentum / Fighter Heat** | We have `fighter_marketability` but should add a **momentum** sub-stat (recent-results-based, -5 to +5 scale) that's distinct from base marketability. Two high-momentum fighters matched up = draw bonus. This is a non-obvious lever the player can exploit. |
| **Hype slider (risk/reward)** | Add a per-fight "Push" slider (None / Light / Heavy) that boosts the popularity gain for the winning fighter but magnifies the loss for the loser. Story-rich. |
| **Quick Move Fight** | A button on each booked fight to move it to another scheduled event without cancel/rebook. Auto-checks training camp dates + willingness. |
| **Replacement Offers** | When a booked fighter is injured, trigger private offers from eligible rostered fighters (via the mail/news system). Player accepts/rejects. The offering fighter won't turn down the fight if accepted within 7 days. |
| **Rankings ≠ Popularity** | Keep our `rankings` table (skill-based) separate from `fighters.marketability` (popularity-based). Surface BOTH on the matchmaking screen, with a tooltip explaining the distinction. A #1-ranked fighter with low marketability is a *story to develop*, not a bug. |

### 7.2 What to IMPROVE on (where WMMA5 falls short)

| WMMA5 weakness | CAGE EMPIRE improvement |
|---|---|
| **No live attendance / buyrate / revenue projection** | **The headline feature.** Wire the matchmaking screen into `get_event_preview` so the projected P&L updates live as fights are added/removed/reordered. Replace the hardcoded `card_draw = 1.2` (in `app_web.py::get_event_preview` line ~2814) with the real `card_draw_multiplier` formula from `finance.py::_compute_broadcast_revenue`. Show: projected attendance, projected PPV buys, projected gate, projected net profit — all colour-coded (green/yellow/red). |
| **Compare is text-only** | Build a **visual tale-of-the-tape**: side-by-side radar chart of the 25 attributes, plus height/reach/age/record/style chips. PLUS the natural-language analysis from the voice layer. Best of both worlds. |
| **No ranking implications prediction** | Add a "What's at Stake" panel below each booked fight: *"If Reed (rank #7) wins → projected rank #3. If he loses → projected rank #11."* Also: *"Winner is in line for a title shot against champion Vale."* |
| **Prelims have zero impact** | Give prelims a small but nonzero contribution to the projected commercial rating (e.g., 5% weight on the undercard's average marketability). This rewards players who build deep cards and makes prelim booking feel meaningful. |
| **No drag-and-drop reordering** | Use a JS drag-drop library (or native HTML5 drag-drop) for card reordering. Visual feedback during drag (slot highlights). Auto-snaps to main-event / co-main / main-card / prelim zones. |
| **No smart matchup suggestions** | Add a "Suggested Matchups" panel that surfaces 3–5 specific matchups based on: ranking proximity, momentum matching, style contrast (striker vs grappler = exciting), rivalry heat, title-shot implications. Each suggestion is one-click-bookable. Still opt-in — the player can ignore all suggestions. |
| **No card coherence feedback** | Add a "Card Health" indicator that flags: too many fights in one weight class, too many strikers (repetitive stylistically), no title fight on a PPV, main event weaker than co-main. Voice-layer explanation: *"Your main event is drawing less interest than your co-main — consider swapping them."* |
| **Card-placement advice is one-dimensional** | Compute card-placement advice *per matchup* (not per fighter), factoring in both fighters' marketability + the company's size tier. Explain *why*: *"This is a credible co-main for a Mid Regional promo — Reed's marketability (62) + Vale's (55) puts it in the co-main band."* |
| **Critical Rating doesn't explain itself** | Post-event, surface a voice-layer breakdown: *"Card rated 73/100 — the Watson vs King fight stole the show (fight rating 91), but the main event went to a lacklustre decision (fight rating 54) and dragged the overall down."* |
| **Ticket pricing is automatic** | We already have a ticket-price slider in `event_builder.js`. Keep it. Add a "Recommended" badge showing the AI-suggested price based on company size + region, so the player has a baseline. |
| **Information overload** | Consolidate. The matchmaking screen should be a single page with: 2-column picker (left), card builder (center), live projection + adviser (right). No separate screens for Search/Rankings/Titles/Absences — inline panels or modals. |
| **No tale-of-the-tape graphic** | Add a tale-of-the-tape graphic that mimics the UFC broadcast style: two fighter portraits side by side, height/reach/age/record/style/last-5-fights between them. This is both immersive and instantly readable. |

### 7.3 Specific features for our matchmaking screen

The matchmaking screen (`src/web/js/matchmaking.js` — to be created; nav
item already exists at `app.js` line 43 with icon ⚔) should have:

#### Layout (3-column, single screen)

```
┌──────────────┬─────────────────────────────────┬──────────────────┐
│  ROSTER      │  CARD BUILDER                   │  LIVE PROJECTION │
│              │                                 │                  │
│ Weight Class │  RED CORNER    BLUE CORNER      │  Projected Draw  │
│ [▼ Feather]  │  ┌────────┐   ┌────────┐        │  ★★★★☆ (74)      │
│              │  │ portrait│   │ portrait│        │                  │
│ Search:      │  │ REED   │   │ VALE   │        │  Attendance      │
│ [_______]    │  │ #7 LW  │   │ #11 LW │        │  ~8,400 / 12,000 │
│              │  │ 18-4   │   │ 12-3   │        │                  │
│ Filters:     │  └────────┘   └────────┘        │  PPV Buys        │
│ □ Available  │                                 │  ~125,000        │
│ □ Top 15     │  [Compare] [Fan Pulse]          │                  │
│ □ On streak  │  [Tale of Tape] [What's at      │  Gate: $672k     │
│              │   Stake]                        │  PPV:  $3.1M     │
│ ─────────    │                                 │  Costs: $1.2M    │
│ 1. Reed ★    │  Push: [None|Light|Heavy]       │  ────────────    │
│ 2. Vale ★    │                                 │  NET:  $2.6M     │
│ 3. ...       │  [Add to Card]                  │  (green)         │
│              │                                 │                  │
│              │  ─── CURRENT CARD ───           │  Card Health:    │
│ [Adviser ▼]  │  1. (ME) Reed vs Vale   ★★★★☆  │  ✓ Main event OK │
│ • Hometown   │  2. (CoM) Santos vs Kim  ★★★☆☆ │  ✓ Title fight   │
│ • Win streaks│  3. (MC)  Watson vs King ★★☆☆☆ │  ⚠ 4 of 5 fights │
│ • Debuts     │  4. (MC)  ...                   │    are strikers  │
│ • Title pic  │  5. (Pre) ...                   │  ✓ Spread of WC  │
│              │                                 │                  │
│              │  [Drag to reorder]              │  [Suggested      │
│              │                                 │   Matchups ▼]    │
└──────────────┴─────────────────────────────────┴──────────────────┘
```

#### Required components

1. **Roster list (left column)**
   - Weight-class filter
   - Search box
   - Filter checkboxes: Available (not injured/suspended/booked), Top 15,
     On Win Streak, Hometown (for selected venue region)
   - Each fighter row: portrait + name + rank + record + marketability chip
     + momentum flame icon
   - Click → populates next available corner slot (red, then blue)

2. **Card builder (center column)**
   - 2-column RED CORNER / BLUE CORNER picker
   - Per-fight buttons: Compare, Fan Pulse, Tale of Tape, What's at Stake
   - Push (hype) slider per fight
   - Add to Card button
   - Card list with drag-drop reordering
   - Each fight shows: 0–5★ Draw rating + title chip + rivalry chip +
     inducements icon
   - Auto-zones: Main Event / Co-Main / Main Card / Prelims

3. **Live projection (right column)** — **THE key improvement over WMMA5**
   - Projected Draw (0–100, with star equivalent)
   - Projected Attendance vs venue capacity
   - Projected PPV buys (if PPV toggled)
   - Gate / PPV revenue / costs / NET profit (colour-coded)
   - Card Health checklist (main event strength, title fight present,
     stylistic diversity, weight-class spread, card-length penalty)
   - Suggested Matchups panel (3–5 one-click-bookable suggestions)
   - Booking Adviser collapsible (hometown, streaks, debuts, title picture)

4. **Modals (opened from card builder)**
   - **Compare modal**: visual radar chart of 25 attributes + natural-language
     style matchup analysis from the voice layer
   - **Tale of Tape modal**: UFC-style graphic (portraits + height/reach/age/
     record/style/last-5)
   - **What's at Stake modal**: ranking implications for both fighters
     (win → projected rank, lose → projected rank; title-shot proximity)
   - **Fan Pulse modal**: one-line voice-layer reaction + breakdown of why
     (marketability × ranking gap × rivalry heat × momentum)

#### Data plumbing required

- Replace `card_draw = 1.2` in `app_web.py::get_event_preview` with the
  real `card_draw_multiplier` from `finance.py::_compute_broadcast_revenue`.
- Add a `project_card_draw(card_fights)` function in a new
  `src/services/matchmaking.py` (player-facing, distinct from the AI
  matchmaking service that already exists) that takes a list of booked
  fights + main-event designation and returns:
  - `projected_commercial_rating` (0–100)
  - `projected_quality_rating` (0–100, from fighter attributes)
  - `projected_attendance` (from venue capacity × popularity × card_draw)
  - `projected_ppv_buys` (if PPV toggled)
  - `card_health_flags` (list of warnings)
  - `suggested_matchups` (list of 3–5 matchup dicts)
- Add a `momentum` field to fighters (or derive from recent fight
  history: last 3 fights, weighted by recency + finish type)
- Wire the matchmaking screen into `app.js::navigate()` switch (currently
  the `matchmaking` case is missing — falls through to "coming soon")

### 7.4 How to make matchmaking the "heartbeat" of the game (rewarding, not easy)

Per the CAGE_EMPIRE_SOUL.md: *"The fighter is not the reward. The STORY
is the reward."* Matchmaking should generate stories, not just
matchups. Specific design moves:

1. **Every matchup should have a "story" the voice layer can tell.**
   When the player books Reed vs Vale, the Fan Pulse shouldn't just say
   *"fans think this is a worthy main event"* — it should say *"Reed
   hasn't fought since the Vale controversy last summer. Fans have been
   waiting for this."* The interpretation layer should mine the memory
   engine for narrative hooks.

2. **Momentum should be a visible, exploitable lever.** Two fighters on
   +5 momentum streaks matched up = draw bonus + a "this is the fight
   to make" voice-layer nudge. This rewards players who pay attention
   to recent results, not just rankings.

3. **Hype should be a risk/reward story generator.** When the player
   pushes a fighter heavy and that fighter loses, the post-event story
   should be *"Watson was supposed to be the next big thing. One punch
   changed everything."* — not just a popularity number change.

4. **Ranking implications should create anticipation.** Showing *"if
   Reed wins, he's in line for a title shot against Vale"* turns a
   random fight into a contender bout. The player can *build toward*
   title fights across multiple events, planning 3 ahead (the
   "pyramid booking" pattern from the forum).

5. **Card coherence feedback should teach the player to be a better
   booker.** *"Your main event is weaker than your co-main — consider
   swapping"* is the kind of feedback that turns a new player into a
   veteran. WMMA5's players had to learn this from forum threads; we
   can teach it inline.

6. **Replacement Offers should generate underdog stories.** When a
   fighter steps up on short notice and wins, that's a storyline the
   memory engine should flag for legacy/hall-of-fame consideration.

7. **Post-event, the rating explanation should be a story, not a
   number.** Instead of "Commercial Rating: 78", surface: *"The Reed
   vs Vale main event delivered — fans got the war they were promised.
   But the undercard fell flat, and three decisions in a row tested
   the crowd's patience."* The voice layer already exists for this.

8. **Matchmaking should NOT be auto-bookable.** Reddit is explicit:
   *"Matchmaking is the most enjoyable aspect of the game, why let an
   AI do it."* We should resist any pressure to add a "auto-book card"
   button. Suggestions yes; auto-book no. The player's judgement is
   the point.

---

## 8. Summary — The WMMA5 → CAGE EMPIRE Translation Table

| WMMA5 feature | Keep / Improve / Replace | CAGE EMPIRE action |
|---|---|---|
| 2-column blue/red corner layout | **Keep** | Default layout for our matchmaking screen |
| Compare button (text analysis) | **Improve** → visual radar + voice-layer NL | Add radar chart + voice-layer analysis |
| Fan Feedback button | **Keep + Improve** → "Fan Pulse" with voice-layer story hooks | Mine memory engine for narrative context |
| Side-panel DRAW stars | **Keep** | 0–5★ per fight, live-updating |
| Booking Adviser tabs | **Keep** | Hometown / Win streaks / Debuts / Title picture |
| 2-rating split (Commercial vs Critical) | **Keep** | Project Commercial + Quality pre-event; rate all 5 axes post-event |
| Momentum / Fighter Heat | **Keep** | Add `momentum` field; surface as flame icon |
| Hype slider | **Keep** | Per-fight "Push" slider (None/Light/Heavy) |
| Quick Move Fight | **Keep** | Move fight between scheduled events |
| Replacement Offers | **Keep** | Mail/news trigger when booked fighter injured |
| Rankings ≠ Popularity | **Keep** | Surface both; tooltip explains distinction |
| **No live P&L projection** | **REPLACE** | Live projection is the headline feature |
| **Text-only Compare** | **REPLACE** | Visual tale-of-tape + radar chart |
| **No ranking implications** | **REPLACE** | "What's at Stake" panel per fight |
| **Prelims have zero impact** | **IMPROVE** | Small nonzero commercial contribution |
| **Arrow-button reordering** | **REPLACE** | Drag-drop |
| **No smart suggestions** | **REPLACE** | "Suggested Matchups" panel (3–5 one-click) |
| **No card coherence feedback** | **REPLACE** | "Card Health" checklist + voice-layer warnings |
| **One-dimensional card-placement advice** | **IMPROVE** | Per-matchup advice (both fighters' marketability) |
| **Critical Rating doesn't explain itself** | **IMPROVE** | Voice-layer post-event breakdown |
| **Automatic ticket pricing** | **REPLACE** | Keep our slider; add "Recommended" badge |
| **Information overload** | **REPLACE** | Single 3-column screen; modals not separate screens |
| **No tale-of-tape graphic** | **REPLACE** | UFC-style tale-of-tape modal |
| **No pre-event card-quality score** | **REPLACE** | Projected Commercial Rating (live) |
| **Auto-book for player** | **REJECT** | Suggestions yes; auto-book no (per community) |

---

## 9. Next Actions (for the implementing agent)

1. **Read** `docs/RESEARCH_MATCHMAKING_SHOWRATING.md` (the existing
   pre-research on our matchmaking gap) — it has the exact line numbers
   for the `card_draw = 1.2` hack and the real formula in
   `finance.py::_compute_broadcast_revenue`.
2. **Create** `src/web/js/matchmaking.js` (nav item already exists in
   `app.js` line 43; wire it into `navigate()`).
3. **Create** `src/services/matchmaking_svc.py` (player-facing projection
   service — distinct from the existing `src/services/matchmaking.py`
   which is the AI auto-pick service).
4. **Add** `project_card_draw(fights, event_meta)` returning the 4
   projected numbers + card_health_flags + suggested_matchups.
5. **Replace** the `card_draw = 1.2` hardcoded value in
   `app_web.py::get_event_preview` (line ~2814) with a call to
   `project_card_draw`.
6. **Add** a `momentum` field to the fighters table (or a derived view)
   — recent-fight-history-based, -5 to +5 scale.
7. **Build** the Compare modal (radar chart + voice-layer NL), the Tale
   of Tape modal (UFC-style graphic), the What's at Stake modal (ranking
   implications), the Fan Pulse modal (voice-layer reaction).
8. **Build** the Booking Adviser collapsible panel (4 tabs: Hometown,
   Win Streaks, Debuts, Title Picture).
9. **Build** the Suggested Matchups panel (3–5 one-click-bookable
   suggestions based on ranking proximity + momentum + style contrast).
10. **Build** the Card Health checklist (main event strength, title
    fight present, stylistic diversity, weight-class spread, card-length).
11. **Wire** the post-event show-rating breakdown into a voice-layer
    explanation (translate the 5 axes into a paragraph the player
    remembers).
12. **Test** the full loop: book a card → see live projection → run
    event → see post-event rating explanation → compare projection to
    actual → iterate.

---

*End of research document. Total sources: 10 (1 community handbook, 1
developer journal with 175 entries, 1 Steam community guide, 4 Grey Dog
forum threads, 4 Reddit threads, 1 blog). File written to
`docs/RESEARCH_WMMA5_MATCHMAKING.md`.*
