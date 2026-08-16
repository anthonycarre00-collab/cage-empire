> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# Research: WMMA5 + FM Matchmaking V2

**Task ID:** RESEARCH-WMMA5-FM-MATCHMAKING-V2
**Scope:** Targeted re-research of *World of Mixed Martial Arts 5* (Grey Dog
Software, 2018) + *Football Manager* (Sports Interactive) focused on the
five specific user complaints:
1. Fighter popularity / rank / titles / rivalries are invisible when building matchups
2. Matchup sections need to be BIG, BOLD, and EDITABLE
3. Projection is "easy mode" — should be "might" advice only
4. No calendar — player cannot choose WHEN to schedule events
5. Fighter availability + last-minute rejection based on personality is missing

**Why V2:** The V1 research (`docs/RESEARCH_WMMA5_MATCHMAKING.md`) covered
WMMA5 mechanics comprehensively but was written *before* the matchmaking
screen was built. Now that the screen exists and is "fiddly and buggy,"
this V2 doc re-examines the source material with the implementation's
actual gaps in mind. No code changes — research only.

---

## Sources Consulted (this pass)

| Source | URL | What it gave us this pass |
|---|---|---|
| WMMA5 Player's Handbook (re-fetched in full, 125KB plain text) | hansmellman.github.io/wmma5-players-handbook | Verbatim quotes on Scheduling (min 1-month lead, no simultaneous limit, >1-month trade-offs), Event Disruption (-15% penalty, main-event injuries hurt most), Replacement Offers (7-day window, fighters self-offer only if they have something to gain), Inducements (4 categories — opponent/training-time/difficulty/weight-class), Hype (None→Small→Medium→Large risk/reward), Challenges (extremely unlikely to turn down), Personality (drives inducement demands), Name Value, Popularity |
| Existing CAGE EMPIRE code (audited for V2) | `src/web/js/matchmaking.js` (1405 lines), `src/web/css/matchmaking.css` (1328 lines), `src/app_web.py::create_event` (line 3465) | Verified the actual gaps: corner slot renders only portrait/name/record/WC; roster row omits marketability + title chips; `create_event` hardcodes `+14 days` with no player date input; projection surfaces `predicted_method` + `confidence_word` (dangerously close to "easy mode"); sections locked in 300/1fr/340 grid |
| V1 research doc (already in repo) | `docs/RESEARCH_WMMA5_MATCHMAKING.md` | Cross-reference; the WMMA5 screen ASCII layout (§1.1) and dev-journal entry numbers are reused below without re-citation |
| FM Scout — Player Attributes Explained (FM22 guide, fetched in full) | fmscout.com/a-player-attributes-guide-2022.html | Confirms FM's attribute display: 3 sections (technical / mental / physical), rated 1–20, all visible on the player profile screen at a glance. Hidden attributes (consistency, professionalism, injury proneness) exist but are scouted, not shown by default |
| FM Scout community + Sports Interactive forums (snippets via search) | community.sports-interactive.com, fmscout.com | FM player-overview screen packs attributes, role-suitability stars, recent form arrows, and injury status into one panel; users can add columns. Fixture list is a single calendar view with competition color-coding. FM's "squad view" lets you customize 100+ columns |

---

## 1. WMMA5 Fighter Info Display

### 1.1 What's shown when you're picking fighters (per the V1 screen diagram + handbook)

The WMMA5 Match Making screen is a 2-column "blue corner vs red corner"
layout. When a fighter is loaded into a corner, the side panel shows:

| Field | Format | Source |
|---|---|---|
| Portrait | Image | `fighters` |
| Name + nickname | Text | `fighters` |
| Pro record (W-L-D) | Text e.g. "18-4-0" | career fight history |
| Company rank + world rank | Numeric, hover-tooltip expands the full ranking list | `rankings` |
| **Name Value** (popularity tier) | **Text label** — "Mid Level Regional", "Low Level National", "Cult Hero", "Household Name" | `fighters.popularity` |
| Style archetype | Text — "Striker", "Grappler", "Wrestler", "Balanced" | derived |
| Weight class | Text | `weight_classes` |
| Next fight / Last fight | Text (defaults to last fight if nothing scheduled — dev-journal #110) | `fights` |
| **Likely Usage** | Text approximation of "popularity and worth to the company" (dev-journal #146) | derived |
| **Momentum / Fighter Heat** | **Flame icons** — overhauled in dev-journal #77 to factor type/speed of victory, betting lines, world ranking | derived |
| **Inducements icons** | Per-fight icon set — training-time, opponent-specific, difficulty, weight-class | derived |
| Personality + Persona | Visible in profile (dev-journal #149), surfaced in matchmaking via inducement behaviour | `fighters.personality` |
| Popularity change arrows | Visible post-event (dev-journal #108/#109) | derived |

So WMMA5's corner panel is **denser than ours**. The non-obvious
specifics the user is asking about:

- **Popularity IS shown** — but as a *text label* ("Cult Hero",
  "Mid Level Regional"), not a number. The label IS the popularity
  tier, derived from `fighters.popularity`. Players read it like a
  marketing tier, not a stat.
- **Rank IS shown** — as a number (`#7`) in the side panel, with a
  hover tooltip that opens the full rankings list.
- **Titles ARE shown** — via a separate "Titles" button below the
  fighter; the current champion per weight class is listed there.
  To put a title on the line, you set the "Title on the line"
  dropdown at the top *before* clicking Add.
- **Rivalries ARE shown** — but indirectly, via the "Heat" reading on
  the matchup (dev-journal #77 + the handbook's "Challenges" and
  "Trash Talking" sections). A challenge ("I want to fight X")
  generates heat that shows up in the side-panel draw stars.

### 1.2 Tale of the tape comparison

**No.** WMMA5's Compare button is **text-only** — a paragraph of
natural-language analysis like *"striker vs grappler matchup, X's
wrestling matches up to Y's, he should win if he avoids being taken
down"*. There is **no visual radar chart**, no side-by-side stat
bars, no height/reach/age comparison graphic. This is WMMA5's biggest
display weakness — and an opportunity we already plan to seize.

### 1.3 What's NOT shown clearly (even in WMMA5)

The handbook is candid that several things are confusing:

- The "prelim level" advice is per-fighter, not per-matchup. Veterans
  on the Grey Dog forum explicitly tell new players to *"ignore the
  game any time it tells you a fight should be on the prelims"*.
- Rankings ≠ popularity — Adam Ryland had to step into a forum thread
  to clarify that rankings are skill, name value is draw. The game
  communicates *that* they differ but not *why*.
- No "ranking implications" prediction — the player has to mentally
  track the contender ladder.

### 1.4 Implications for the user's complaint #1

The user is right that **our corner slot is thinner than WMMA5's**.
Today our `renderCornerSlot()` (matchmaking.js line 288) shows:
portrait, name, record, weight class. **Missing vs WMMA5**: name
value / popularity tier label, rank chip, title chip, momentum/heat
flame, rivalry indicator, inducement icons, "likely usage" phrase.
The roster row (line 232) does show rank_str + momentum_short +
streak_phrase, but **marketability / popularity tier is nowhere on
the screen**. That's the core of the user's complaint.

---

## 2. WMMA5 Card Building UX

### 2.1 Section size and layout

WMMA5 is a Windows desktop app from 2018 built on a 2000s-era UI
toolkit. The Match Making screen is **full-window** (not a modal,
not a split). It has:

- A top filter bar (weight class, title-on-the-line dropdown)
- Two large corner panels (blue left, red right) — each ~30% of
  screen width, with portrait, name, record, rank, name value, plus
  the Search/Rankings/Titles/View Profile/Scout buttons below.
- A center strip with the Compare / Fan Feedback / Hype / Add buttons.
- A bottom "Current Card" list taking the lower ~40% of the screen,
  with each fight on its own row showing DRAW stars + Heat +
  Inducements icons + ▲▼ reorder arrows + × remove.

There is **no separate "projection" column** — the card list itself
is where you read draw quality (via the per-fight stars). The
financial projection appears only **after** the event happens.

### 2.2 Add / remove / reorder

- **Add**: click fighter in blue column, click fighter in red column,
  click "Add Match to Card". 3 clicks per fight.
- **Remove**: × button on the right of each fight row.
- **Reorder**: ▲▼ arrow buttons per row (no drag-drop). Moving a
  fight below a certain threshold marks it as Preliminary.
- **Quick Move Fight** (dev-journal #22): a button to move a fight
  to a *different scheduled event* without cancel/rebook — handles
  training-time + willingness recalculation automatically.

### 2.3 Card size

Community consensus: **8 fights minimum** (else penalty), **9–12
typical** (4–5 prelims + 5–6 main card), no hard cap. Some players
run 15 total when roster is bloated. Payroll pressure is the only
natural cap.

### 2.4 Confirm step

**No formal "confirm card" step.** You add fights until you're
happy, then advance the calendar. The "card" is just the set of
fights on the scheduled event. There IS a confirmation when you
cancel a show (financial penalty + stability hit).

### 2.5 Implications for the user's complaint #2 (BIG / BOLD / EDITABLE)

WMMA5's sections are not particularly "big" — but they are
**unambiguous and full-window**. The lesson is not "make it bigger"
per se, but **"don't cram it into a 3-column 300px/1fr/340px grid
the way our current matchmaking.css does"**. Our current layout
locks the left roster column to 300px (matchmaking.css line 29),
which makes fighter rows feel cramped and forces the corner slot
into a thin slice. The user's "BIG and BOLD" complaint is really
"the matchup zone doesn't dominate the screen the way it should" —
WMMA5's corner panels are ~30% of the screen each, our corner slots
are about ~25% of the center column (which itself is ~50% of the
screen), so they feel half the size they should.

**EDITABLE** in WMMA5 means: ▲▼ reorder arrows + × remove + the
Hype slider. Our current screen has drag-drop reordering (good) and
× remove (good) but no Hype slider and no inline card-slot editing.

---

## 3. WMMA5 Analysis/Advice

### 3.1 Does WMMA5 tell you who will win? ("easy mode")

**No — and this is a critical design choice the user is asking us to
preserve.** WMMA5 deliberately does NOT give a winner prediction.
What it gives:

- **Compare button**: a paragraph of *style matchup* natural
  language — "striker vs grappler, X's wrestling matches Y's, he
  should win if he avoids being taken down." This is **conditional
  ("if X happens, Y might win")** advice, not a definitive call.
  The phrase "he should win if…" is the WMMA5 equivalent of our
  desired "might" advice.
- **Fan Feedback button**: one line — "fans think this is a worthy
  main event" / "decent co-main" / "prelim level". This tells you
  whether the fight *belongs* on the card slot you put it in — it
  does NOT tell you who wins.
- **Side-panel DRAW stars** (0–5★): commercial attractiveness of
  the fight. Not a prediction.
- **Likely Usage** (dev-journal #146): a text approximation of the
  fighter's popularity and worth — "main event level", "prelim
  level". Not a prediction.

Crucially, **WMMA5 never shows**:
- A predicted winner.
- A predicted method (KO/sub/dec).
- A "confidence" percentage.
- Win probabilities.

### 3.2 When do financials appear?

**Only after the event happens.** During booking, WMMA5 shows:
- Per-fight DRAW stars.
- Per-fight Fan Feedback.
- Per-fight Inducements (the cost you'll pay).
- Booking Adviser (dev-journal #42) — tabs surfacing opportunities
  (hometown fighters, debuts, #1-contender fights).

It does NOT show projected attendance, projected PPV buys,
projected gate, projected net profit, or a combined card-quality
score. The player books on instinct + per-fight feedback, then sees
the actual numbers post-event. **This is WMMA5's single biggest UX
gap — and the one we're specifically closing.**

### 3.3 Implications for the user's complaint #3 (no easy mode, only "might" advice)

The user is right to flag this. Looking at our current
`renderFightCard()` (matchmaking.js line 344), we surface:
- `bf.matchup_phrase` + `bf.matchup_score` (the chip)
- `analysis.predicted_method` — a **predicted method chip**
- `analysis.confidence_word` — a **confidence chip**
- `analysis.style_edge` or `analysis.excitement_phrase` (voice line)

The first two cross the "easy mode" line. WMMA5 deliberately
refuses to predict a winner or method — we should follow that
principle. Replace `predicted_method` + `confidence_word` with
**purely conditional, "might"-style voice phrases**:

- ❌ "predicted method: KO · conf: high"  ← easy mode
- ✅ "Reed's boxing vs Vale's wrestling — if Reed can keep it
  standing, he's got the chin to weather the early storm" ← might
- ✅ "Two grapplers with submission specialist attributes —
  anticipate ground exchanges; could go long" ← might
- ✅ "Stylistic contrast is sharp — expect swings of momentum" ← might

The matchup **quality** chip (0–100 + voice phrase like "elite
matchup" / "tune-up" / "mismatch") is fine to keep — it's a
*commercial* read, not a *competitive prediction*. WMMA5's DRAW
stars are the equivalent. The line we should not cross is:
**quality = OK to show, predicted winner/method/confidence = NOT OK**.

---

## 4. WMMA5 Scheduling

### 4.1 How does the player choose WHEN to schedule an event?

From the handbook (verbatim, fetched this pass):

> *"You can schedule a new event whenever you like by using the Match
> Making button in your office. There is no limit on how many shows
> you may have scheduled simultaneously. **You must give at least one
> month's time for the show to be organised, except in the first
> week of the game when you only require two weeks of preparation
> time.**"*

> *"The advantage of booking a show more than one month into the
> future is that it may allow you to get shared fighters booked
> before a rival uses them. It also allows the fighters longer to
> hype the fight. The disadvantage is that the longer the fighters
> are scheduled to fight, the greater the chance that they will
> sustain an injury during training."*

> *"Cancelling a show, except on the same day that it was scheduled,
> will cost money (the amount depending on how long it has been
> scheduled) and also damage your Stability rating (the closer you
> are to the show happening, the greater the damage)."*

### 4.2 Is there a calendar view?

WMMA5 has a calendar screen (accessible from Your Office), but it
is **not integrated into the matchmaking screen**. The scheduling
flow is:

1. Click Match Making → Add Event.
2. A popup asks for an event name + a **date picker**.
3. The date picker enforces the 1-month minimum lead (or 2-week in
   the first game week).
4. Once the event is created, you book fights onto it.
5. The calendar screen shows all scheduled events across all
   promotions on a single month-grid view.

So WMMA5 has **two separate surfaces**: the date picker at event
creation, and a calendar view for browsing. They are not the same
screen.

### 4.3 Rival events visible on the same calendar?

**Yes.** The calendar shows all scheduled events from all
promotions. The handbook implies this in the scheduling section
("shared fighters booked before a rival uses them") and the dev
journal's "Combatative AI" entry (#50) confirms rivals actively
compete for fighters. Rival events are visible but the game does
not hard-prevent date collisions — the player can knowingly
counter-program.

### 4.4 How far in advance can you schedule?

**No hard cap.** You can book shows months ahead. The trade-off
(longer lead = injury risk + training camp cost) is the only
natural friction. The 1-month minimum is the only floor.

### 4.5 Restrictions on dates?

- 1-month minimum lead (or 2 weeks in game's first week).
- No explicit holiday restrictions.
- No explicit venue-availability system — venue is picked at
  booking, not at scheduling.
- Cancelling close to the date costs money + stability.

### 4.6 Implications for the user's complaint #4 (calendar/scheduling)

**We have a real gap.** Our `create_event` (app_web.py line 3465)
currently:

```python
event_date = params.get("event_date")
if not event_date:
    if not sim_date:
        return {"ok": False, "error": "No sim clock available."}
    dt = datetime.strptime(sim_date, "%Y-%m-%d")
    event_date = (dt + timedelta(days=14)).strftime("%Y-%m-%d")
```

So if the player doesn't pass a date, we default to `+14 days`.
The event_builder.js screen doesn't currently render a date picker
at all — the player has no UI control over when the event happens.
This is a regression vs WMMA5 and a clear user complaint.

The fix is to add a **calendar/date-picker component** to the
Stack a Card screen (or as a separate scheduling step) — see §7
for the specific recommendation.

---

## 5. WMMA5 Fighter Availability

### 5.1 Injured / suspended / already-booked fighters

- **Absences button** on the Match Making screen (dev-journal #144)
  lists every currently-unavailable fighter in one place. The
  handbook describes it as *"makes match making easier and has been
  requested a lot."*
- Injured and suspended fighters are **filtered out** of the
  selectable roster automatically.
- Already-booked fighters simply don't appear in the picker for the
  date range of the event you're booking.

### 5.2 Can injured/suspended fighters be booked?

**No** — they're filtered out. The handbook is unambiguous.

### 5.3 "Needs training camp" requirement

Implicit. Every booked fight triggers a training camp (the dev
journal #22 Quick Move Fight feature explicitly recalculates
"existing training times"). The 1-month minimum lead exists
*because* fighters need camp time. There's no separate "request
training camp" action — booking the fight IS booking the camp.

### 5.4 Last-minute rejection based on personality — THE key question

WMMA5 does this via **three interlocking systems**:

**A. Inducements (financial, per-fight).** From the handbook:

> *"When match making, fighters may ask for financial inducements in
> order to take a specific bout. There are four different possible
> categories; inducements to fight a specific opponent, inducements
> related to training time, inducements relating to difficult
> opponents, and inducements for weight classes. In all cases, the
> agreed upon price is paid only when the fight actually happens."*

The inducement icons show on the match making screen per fight.
Personality drives the *size* of the inducement a fighter demands
("some fighters have excessive demands due to their personalities
or other circumstances and may require more").

**B. Challenges (willingness signal).** From the handbook:

> *"A challenge means that that fighter is extremely unlikely to
> turn down the fight if offered."*

So when a fighter publicly challenges another, the game has an
explicit "this fighter is willing" flag.

**C. Replacement Offers (short-notice fill-ins).** From the
handbook:

> *"Fighters will generally only offer themselves as a replacement
> if they have something to gain from the bout (such as a title, a
> chance to move up the rankings, etc). These offers or requests to
> be a replacement are done privately and are not considered the
> same thing as a challenge; they do not affect the 'draw' of the
> fight, nor do they impact the relationship between the fighters.
> If a fighter is forced to withdraw from a bout due to injury then
> other fighters may contact the player to offer themselves as a
> replacement. If this happens, the fighter will be extremely
> unlikely to turn down the fight is it is offered within the
> following seven days. After that seven day period is up, the
> offer is considered to have expired. These offers are done via
> e-mail and are not recorded or shown anywhere else in-game."*

**D. Event Disruption (consequence of late changes).** From the
handbook:

> *"An event's disruption status is a hidden variable. The more
> important the fight being impacted, the greater the disruption.
> For example, a main event getting altered due to injury will
> produce a huge disruption, a prelim fight getting moved will
> cause little or no disruption. The following things count as
> disruptions: fights being cancelled, fights being moved off the
> show, and fights being altered due to one (or both) of the
> competitors becoming unavailable. Adding new fights or filling in
> To Be Announced positions do not count as disruptions. In the
> week immediately before a scheduled event takes place it is
> considered vulnerable to change. During this time period,
> changes may be logged as official 'Event Disruptions'. The more
> disruptions that happen, the more the Commercial Rating will be
> impacted. At its worse, with a severely disrupted show, the
> Commercial Rating may be penalised up to 15."*

So the WMMA5 model is:

1. **Pre-booking**: fighter availability is filtered (injury,
   suspension, already-booked).
2. **At booking**: personality + matchup + camp time + weight class
   drive **inducement demands** (visible icons). Player pays or
   doesn't book.
3. **Post-booking, late withdrawal**: if a fighter withdraws due
   to injury, **other fighters self-offer as replacements via
   email** — but only if they have something to gain (title, ranking
   movement). The offering fighter won't turn the fight down if
   accepted within 7 days.
4. **Consequence**: each late change in the week before the event
   is an Event Disruption — up to -15% Commercial Rating for a
   severely disrupted show, with main-event changes hurting most.

### 5.5 Implications for the user's complaint #5 (availability + last-minute rejection)

We currently have injury filtering (the eligible-fighters query
excludes injured/suspended fighters, per `services/matchmaking.py::
_get_available_fighters_for_card`). We do NOT have:

- An **Absences panel** — a single place to see who's unavailable
  and why.
- **Inducements** — per-fight personality-driven extra-cost demands.
- **Replacement Offers** — when a booked fighter withdraws, no
  other fighters self-offer to step in.
- **Event Disruption** — no penalty model for late card changes.
- **Personality-driven rejection** — fighters don't turn down
  matchups; the player can book anyone eligible against anyone
  eligible in the same WC.

This is a real, multi-system gap. The WMMA5 model is rich enough
that we can pick which pieces to lift. Recommended priority is in
§7.

---

## 6. Football Manager Parallels

### 6.1 How FM shows player info when building a lineup

FM's player profile screen (verified via fmscout.com guide fetched
this pass) shows attributes in **three clearly-labelled sections**:

- **Technical** (or Goalkeeping for keepers): finishing, passing,
  tackling, marking, technique, etc.
- **Mental**: aggression, bravery, composure, concentration,
  decisions, determination, flair, leadership, work rate, etc.
- **Physical**: acceleration, agility, balance, jumping, natural
  fitness, pace, stamina, strength.

Each attribute is rated **1–20** (whole numbers on screen, but the
engine uses 2 decimal places internally). The display is dense but
readable — a single screen-filling panel packs all 30+ attributes
plus role-suitability indicators.

Crucially, FM's **squad view** (the screen you use to pick a
lineup) is a **customizable table** with 100+ optional columns:
attributes, form arrows, condition %, morale, injury status,
recent match ratings, contract status, value, wage. The player
configures the columns once and the squad view becomes their
personal scouting dashboard. This is the FM equivalent of "BIG and
BOLD and EDITABLE" — the player chooses what's visible.

### 6.2 How FM handles match scheduling

FM's fixture list is a **calendar view** with competition
color-coding — league games one color, domestic cups another,
continental competition another. The player can see the entire
season at a glance, with rest days highlighted and fixture
congestion flagged (e.g., "3 games in 7 days" warnings). The
calendar is a single screen, not a popup.

### 6.3 What we can learn from FM's UX clarity

| FM principle | How it applies to CAGE EMPIRE |
|---|---|
| **Dense, single-screen attribute display** | Our fighter profile should pack 25 attributes + marketability + momentum + rank + title + recent form into one screen, not require 4 modal clicks. |
| **Customizable columns** | The matchmaking roster list should let the player toggle columns (rank, marketability, momentum, streak, hometown, last fight date). The current fixed `name + WC + record + momentum + streak + rank` row is fine as default but should be configurable. |
| **Form arrows + condition %** | FM shows recent form as up/down arrows next to each player. We already have `momentum_short` (e.g., "+3" / "-2") — surfacing it as a colored arrow (▲ green / ▼ red) next to the fighter name would be more scannable than the current chip. |
| **Color-coded calendar** | When we add the calendar, color-code by event type (fight night / PPV / title night) and by promotion (player vs rivals). |
| **Fixture congestion warnings** | When we add scheduling, flag if a fighter would be booked twice within X days (camp conflict, injury risk). |
| **Injury status inline** | FM shows injury status directly in the squad list (red cross icon + days-out estimate). We currently filter injured fighters out entirely; an Absences panel (WMMA5-style) plus an "injured" indicator on the roster would be better. |
| **Role-suitability stars** | FM shows 1–5 stars for how well a player fits a role. We could show "main event suitability" / "co-main suitability" / "prelim suitability" stars per fighter based on marketability × company size_tier (this is literally WMMA5's "Likely Usage" concept, executed FM-style). |

### 6.4 The FM lesson in one sentence

**FM's clarity comes from putting every relevant signal on one
screen, configurable by the player, with visual indicators (stars,
arrows, colors) instead of raw numbers.** That's exactly the
philosophy the user is asking for: BIG, BOLD, EDITABLE.

---

## 7. Recommendations for CAGE EMPIRE

The user's five complaints, mapped to specific improvements, with
priority order.

### Priority 1 — Fighter info display (complaint #1)

**Problem:** Corner slot shows only portrait/name/record/WC.
Roster row omits marketability. No title chips, no rivalry
indicators.

**Fix — make the corner slot BIG and INFORMATION-DENSE:**

Each corner slot should show (top-to-bottom):
1. **Portrait** (large, ~120×120px — current is ~80×80)
2. **Name + nickname** (display font, 18px)
3. **Rank chip** — `#7 LW` (gold if champion, silver if top-5)
4. **Title chip** — `🥇 LW Champion` or `—` (visible AT ALL TIMES, not buried in a modal)
5. **Popularity tier label** — text like WMMA5's "Cult Hero" /
   "Mid Level Regional" / "Household Name" (voice-layer phrased,
   derived from `fighters.marketability`)
6. **Momentum flame** — colored arrow ▲/▼ + number (-5 to +5)
7. **Record + WC + age + style archetype** — single dense line:
   `18-4-0 · LW · 28y · Striker`
8. **Rivalry indicator** — if these two fighters have a rivalry
   (heat ≥ 50), show a `⚔ RIVALRY` chip on the center "VS" strip
9. **Recent form** — last 5 fights as W/L/D chips (green/red/grey)

The roster list row should mirror this density (configurable
columns per FM) — but the corner slot is where it matters most
because that's where the player is *making the decision*.

### Priority 2 — BIG / BOLD / EDITABLE sections (complaint #2)

**Problem:** Current 3-column 300px/1fr/340px grid makes the
corner slots feel cramped.

**Fix — restructure the layout:**

Option A (recommended): **Two-row layout.**
- **Top row (60% height):** the matchup zone — Red Corner | VS
  strip | Blue Corner. Each corner takes ~45% of the width. BIG
  portraits, BIG name, dense info panel. This is the decision
  zone — it should dominate.
- **Bottom row (40% height):** split into Card List (left 60%)
  + Live Projection (right 40%).

Option B: **Modal-first matchup picker.** Click "Stack a Fight"
→ opens a fullscreen modal with the two corners + compare/tape/
stakes/pulse buttons. Card list + projection stay on the main
screen underneath. (This is closer to WMMA5's flow.)

Either way, the corner slots need to be **~2× their current visual
size**. The current `grid-template-columns: 300px 1fr 340px`
(matchmaking.css line 29) is the constraint — break it.

**EDITABLE means:**
- Inline card-slot editing (click a fight's slot label → dropdown
  to change main_event / co_main / featured_prelim / prelim /
  opener — no drag required).
- Inline hype/push slider per fight (None / Light / Heavy —
  WMMA5's Hype slider).
- Inline title-on-the-line toggle per fight.
- Drag-drop reordering (already have it — keep).
- × remove (already have it — keep).

### Priority 3 — "Might" advice, NOT easy mode (complaint #3)

**Problem:** Current `renderFightCard()` surfaces
`analysis.predicted_method` + `analysis.confidence_word` — that's
"easy mode".

**Fix — strip the prediction chips, keep only conditional voice:**

Remove from the fight card UI:
- ❌ `analysis.predicted_method` chip ("predicted: KO")
- ❌ `analysis.confidence_word` chip ("conf: high")

Keep / add:
- ✅ `bf.matchup_phrase` + `bf.matchup_score` chip — this is a
  *commercial* read ("elite matchup" / "tune-up" / "mismatch"),
  equivalent to WMMA5's DRAW stars. OK to keep.
- ✅ `analysis.style_edge` — conditional voice phrase: "Reed's
  boxing vs Vale's wrestling — if Reed can keep it standing…"
- ✅ `analysis.excitement_phrase` — "anticipate ground exchanges;
  could go long" / "stylistic contrast is sharp; expect swings".
- ✅ A new "What to Expect" line per fight — 1 sentence of
  conditional, "might"-style voice. NEVER a definitive prediction.

The principle (matching WMMA5): **the engine may know who's
likely to win, but the UI must never say so.** Quality = OK.
Method/confidence/winner = NOT OK.

The punditry engine (`punditry.py::generate_matchup_analysis`)
already produces `style_edge` and `excitement_phrase` — we just
need to stop surfacing the `predicted_method` / `confidence_word`
fields in the chip row. The backend can keep computing them for
internal use (AI matchmaking, news generation); the UI just
doesn't show them.

### Priority 4 — Calendar / scheduling (complaint #4)

**Problem:** `create_event` defaults to `+14 days`. No UI for
choosing a date. No rival-event visibility.

**Fix — three pieces:**

**A. Date picker on Stack a Card screen.** Add a date input
(default = sim_date + 30 days, matching WMMA5's 1-month minimum).
Validate: ≥ 14 days out (matching our current 14-day default,
more lenient than WMMA5's 1-month for faster early-game pace).
Pass `event_date` explicitly to `create_event` (the param is
already accepted at app_web.py line 3503, just not sent by the
UI).

**B. Calendar view (new screen or modal).** Month-grid showing:
- Player's scheduled events (gold).
- Rival promotions' scheduled events (red, with promo logo).
- Today's date (highlighted).
- Min-lead-time boundary (greyed-out dates < 14 days out).
- Click any eligible date → pre-fills the date picker on Stack a Card.

This is the single biggest scheduling improvement we can make.
WMMA5 has a calendar screen but it's separate from matchmaking;
we should integrate them.

**C. Conflict warnings.** When the player picks a date:
- If a rival promo has an event within ±2 days, show a warning:
  *"Rival Fight League is running 'RFL 47' on Sat —
  counter-programming will split the gate."* (WMMA5 doesn't do
  this; this is a "do better" item.)
- If the player's own promo has an event within 7 days, warn:
  *"You're already running 'CE 12' on Fri — short turnaround."*

### Priority 5 — Fighter availability + last-minute rejection (complaint #5)

**Problem:** No inducements, no replacement offers, no event
disruption, no personality-driven rejection.

**Fix — phased approach (WMMA5 has 4 systems; we should build
them in order of impact):**

**Phase 1 (highest impact, lowest effort): Event Disruption
penalty.**
- Add an `event_disruption_score` column (0–15) to events.
- In the week before the event, any fight removal/replacement
  increments the score (main_event = +5, co_main = +3, main_card
  = +2, prelim = +1).
- Apply `-disruption_score%` to the post-event Commercial Rating.
- Surface the current disruption score on the matchmaking screen
  once the event is within 7 days.

**Phase 2: Absences panel.**
- A collapsible panel on the matchmaking screen listing every
  currently-unavailable fighter + reason (injury / suspension /
  already-booked) + return date.
- One-click filter to show only available fighters (already
  implicit in our eligible-fighters query, but make it visible).

**Phase 3: Personality-driven inducements.**
- When the player books a fight, compute an inducement cost based
  on: opponent difficulty (ranking gap), training-time available
  (< 4 weeks = inducement), weight-class mismatch, fighter
  personality (high-ego fighters demand more for tough opponents;
  low-confidence fighters demand more for short-notice).
- Show inducement icons on the fight card row (per WMMA5).
- Add inducement cost to the projected expenses in the live
  projection (so the player sees the financial impact of booking
  a tough fight on short notice).

**Phase 4: Replacement Offers.**
- When a booked fighter withdraws (injury during camp), trigger
  private offers from eligible rostered fighters via the news
  system.
- Eligibility: fighter must have something to gain (title shot,
  ranking move, debut opportunity). Personality drives
  willingness — ego-driven fighters self-offer more; conservative
  fighters don't.
- Player accepts/rejects via news item. If accepted within 7
  days, the offering fighter won't turn it down.
- This is the most narrative-rich of the four systems — it
  generates underdog stories, short-notice heroics, late-notice
  upsets. Aligns with the Soul doc's "story is the reward"
  principle.

**Phase 5 (lowest priority): Personality-driven rejection of
bookings.**
- WMMA5 doesn't actually do this — fighters don't refuse bookings
  pre-fight; they just demand inducements. The "rejection"
  happens post-booking (withdrawal) or via the inducement cost
  being so high the player chooses not to book.
- For CAGE EMPIRE, we could add a soft version: if a fighter's
  personality + the matchup difficulty + the camp time produce
  an inducement >X% of base purse, the fighter "hesitates" —
  shown as a warning chip on the matchup ("Reed is reluctant —
  inducement may apply"). The player can still book, but is
  warned. This is a "do better than WMMA5" item, not a copy.

---

## 8. Summary — V2 Translation Table

| User complaint | WMMA5 does it? | We currently do it? | V2 action |
|---|---|---|---|
| Can't see popularity/rank/titles/rivalries when matching up | Yes (text label + rank + Titles button + Heat) | Partial (rank on roster only; no marketability; no title chip; no rivalry indicator) | **Priority 1**: dense corner slot with all 9 fields listed in §7.P1 |
| Section not BIG/BOLD/EDITABLE | Full-window 2-column with ~30% corner panels | 3-col 300/1fr/340 grid, corners feel cramped | **Priority 2**: restructure to 2-row layout (matchup zone 60% top, card+projection 40% bottom); inline slot/hype/title editing |
| Easy-mode analysis (predicted winner/method/confidence) | NO — only conditional "might" voice ("he should win if…") | YES — `predicted_method` + `confidence_word` chips shown | **Priority 3**: strip prediction chips; keep quality chip + conditional voice phrases only |
| No calendar / can't choose event date | YES (date picker at event creation + separate calendar screen showing rival events) | NO — `create_event` defaults to +14 days, no UI | **Priority 4**: date picker on Stack a Card + month-grid calendar with rival events + conflict warnings |
| No fighter availability / last-minute rejection based on personality | YES (Absences panel + Inducements + Replacement Offers + Event Disruption) | Partial (injury filter only) | **Priority 5**: phased build — Event Disruption (P5.1) → Absences panel (P5.2) → Inducements (P5.3) → Replacement Offers (P5.4) → Personality rejection (P5.5) |

---

## 9. Next Actions (for the implementing agent)

This is research only — no code. The implementing agent should:

1. **Read this doc alongside** `docs/RESEARCH_WMMA5_MATCHMAKING.md`
   (V1) — V1 has the full source citations and the screen-by-screen
   WMMA5 layout; V2 is the targeted "what to fix now" doc.
2. **Read the current matchmaking screen** (`src/web/js/matchmaking.js`
   + `src/web/css/matchmaking.css`) to see exactly what's there.
3. **Read `app_web.py::create_event`** (line 3465) to see the
   `+14 days` default that needs to be replaced with a player-chosen
   date.
4. **Read `punditry.py::generate_matchup_analysis`** to see which
   fields are prediction-flavoured (predicted_method,
   confidence_word) vs might-flavoured (style_edge,
   excitement_phrase) — the UI should surface only the latter.
5. **Plan the work in the 5 priorities above.** Priority 1 + 3 are
   pure UI changes (no backend). Priority 2 is UI restructuring.
   Priority 4 needs a calendar component + a small backend change
   to `create_event` (already accepts `event_date` — just needs
   the UI to send it). Priority 5 is the biggest build — phase it.

---

*End of V2 research document. Sources: 1 handbook (re-fetched
verbatim), 1 FM guide (fetched verbatim), V1 research doc
(cross-referenced), CAGE EMPIRE source code (audited). File
written to `docs/RESEARCH_WMMA5_FM_V2.md`.*
