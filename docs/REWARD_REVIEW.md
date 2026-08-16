> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Player Reward Review & Application Plan

> **Task ID:** REWARD-REVIEW
> **Status:** RESEARCH + PLANNING ONLY. No code or DB changes.
> **Authored:** against GPT's "Player Reward" design directive
> (`/home/z/my-project/upload/Cage GPT Revolution.txt`) and the 4
> existing screen renderers in `src/web/js/`.
> **Prime directive:** `docs/CAGE_EMPIRE_SOUL.md` — the 5 fantasies.
> The player does not collect fighters; the player collects stories.
> Every recommendation below reinforces that.

---

## 0. Executive Summary

GPT's directive names **5 player rewards** (Discovery, Ownership,
Progression, Emotional Attachment, Agency) plus an additional
**"every screen has at least one hook"** directive. The current 4
screens are **voice-rich** (identity strips, momentum phrases,
ceiling "?" scouting) but **reward-poor**: they translate simulation
into prose well, but they rarely make the player feel like an owner
of consequences.

Across the 4 screens:
- **Best:** Fighter Profile (Attachment 8/10) — identity strip + bio +
  opponent hyperlinks already implement GPT's hook principle.
- **Weakest:** Roster (3/10 average) — a clean table with no story
  layer, no decision callbacks, no emergent hooks.
- **The single highest-impact improvement:** Add an **"Echoes"** data
  channel that surfaces, on every Advance Day, 2-3 consequences of
  the player's past bookings/signings/cuts — and wire them as
  hyperlinks throughout Dashboard and Fighter Profile. This is the
  Agency reward, currently almost entirely missing.

---

## 1. GPT's 5 Player Rewards — Applied to Each Screen

For each cell: **(current state → missing → recommendation)**.
Scores (1-10) reflect how well the reward is currently delivered.

### Reward Matrix — Scores

| Reward               | Dashboard | Roster | Free Agents | Fighter Profile |
|----------------------|:---------:|:------:|:-----------:|:---------------:|
| Discovery            | 6         | 3      | 5           | 7               |
| Ownership            | 5         | 4      | 5           | 5               |
| Progression          | 4         | 3      | 3           | 6               |
| Emotional Attachment | 7         | 4      | 3           | 8               |
| Agency               | 3         | 3      | 3           | 5               |
| **Average**          | **5.0**   | **3.4**| **3.8**     | **6.2**         |

---

### 1.1 Discovery

**Dashboard (6/10)**
- *Current:* Top Story card with topic badge + fighter link; Recent
  News list (10 topics); Fighter Watch 3-card carousel with momentum
  phrases; Recent Results grid.
- *Missing:* No cross-promo discovery (rival promotions invisible).
  Recent Results cards have **no click-through** — a clear hook gap.
  No "rivalry brewing", no "upset in another promo", no "gym
  producing talent".
- *Recommendation:* Add an **"Across the Sport"** mini-section
  surfacing 1 rival-promo headline + 1 comeback + 1 upset. Make every
  Recent Results card a hyperlink to the Fight Resolution / Archive
  screen. Use the existing `news_items` table — filter by
  `promo_id != player_promo_id`.

**Roster (3/10)**
- *Current:* Just a sortable table. There is **nothing to discover**
  — every fighter is one the player already signed.
- *Missing:* No "stable pulse" — the player can't see, at a glance,
  what's *interesting* about their roster right now (3 fighters
  peaking? 2 contracts expiring? a 5-year veteran?)
- *Recommendation:* Add a **"Stable Pulse"** banner above the table:
  2-3 generated phrases ("Three of your welterweights are peaking at
  once", "Iron Forge is producing most of your prospects",
  "Two contracts expire this month"). Each phrase links to a filtered
  view of the roster or to a related screen.

**Free Agents (5/10)**
- *Current:* Ceiling phrases ("Elite", "????") create scouting
  uncertainty — a small discovery reward. But every row is otherwise
  neutral.
- *Missing:* No "an ex-champion just hit the market" or "your rival
  is interested in X". No backstories on individual fighters.
- *Recommendation:* Add a **"Market Pulse"** callout listing 2-3
  emergent stories: "A 19-year-old reportedly with elite ceiling
  appeared today", "Three ex-champions available after rival cuts",
  "Your rival promotion [Name] is reportedly interested in [Name]".

**Fighter Profile (7/10)**
- *Current:* Identity strip with 6 LONG voice phrases (career_phase,
  momentum, pressure, narrative, legacy, trajectory). Fight history
  with opponent hyperlinks enables chain-of-curiosity. Scouting
  report card adds scouting uncertainty.
- *Missing:* No "rivals" callout (which fighters has he fought 2+
  times?). No "stylistic nightmare for" callout. No "trains at
  [Gym] — 4 of his stablemates are also ranked" cross-screen hook.
- *Recommendation:* Add a **"Storylines"** card under the identity
  strip: 2-3 generated phrases each linking elsewhere — "Bad blood
  with [Opponent] — 2 fights, 1 each" → Rivalries; "Trains at [Gym]
  alongside 4 other ranked fighters" → Training Camps.

---

### 1.2 Ownership

**Dashboard (5/10)**
- *Current:* "Welcome back, Promoter." + "THE EMPIRE" gradient
  header + "YOUR CHAMPIONS" section title. Three ownership signals.
- *Missing:* Stat tile labels are all neutral ("CASH", "REPUTATION",
  "FAN TRUST", "ROSTER", "CHAMPIONS"). "RECENT RESULTS" doesn't
  credit the player. "RECENT NEWS" is described as if it's happening
  *to* the world, not *about* the player.
- *Recommendation:* Rename labels — "CASH" → "YOUR WAR CHEST",
  "REPUTATION" → "YOUR STANDING", "RECENT RESULTS" → "CARDS YOU'VE
  RUN", "RECENT NEWS" → "WHAT THE WORLD SAYS ABOUT YOU". Add the
  subtitle "5 titles to capture" beneath the champions count.

**Roster (4/10)**
- *Current:* "THE STABLE" header + "X fighters" subtitle. That's the
  extent of ownership framing.
- *Missing:* Column headers are generic ("Name", "Age", "WC",
  "Stage", "Form", "Record", "Gym", "Nat"). No "your" anywhere.
- *Recommendation:* Subtitle → "X fighters under contract with you".
  Column header "Record" → "RECORD UNDER YOU". Column "Gym" →
  "TRAINING WITH". Add a "Tenure" column showing years-with-promo.

**Free Agents (5/10)**
- *Current:* "OPEN MARKET" header. The sign modal says "Sign [Name]
  to your roster?" — that's the one good ownership phrase.
- *Missing:* No "your scouts recommend", no "your rival wants him",
  no "what he'll cost you".
- *Recommendation:* Modal text → "Bring [Name] into your stable?".
  Sign bar label "ESTIMATED COST" → "WHAT HE'LL COST YOU". Add a
  **"Suggested by Your Scouts"** section: 2 prospects pre-filtered to
  the player's needs (a WC the player is short on, etc.).

**Fighter Profile (5/10)**
- *Current:* Promo line in header is neutral: "[promo_name] ·
  [gym_name]". Action buttons "Cut Fighter" / "Book Next Fight" /
  "Sign to Roster" are good calls to action.
- *Missing:* When the fighter is on the player's roster, no "Fights
  for YOUR promotion" framing. "RECORD" stat tile is generic.
- *Recommendation:* For player-roster fighters: promo line →
  "Fights for YOUR promotion · Trains at [gym]". Stat tile "RECORD"
  → "RECORD UNDER YOUR PROMOTION". Section "TITLE REIGNS" → "BELTS
  HE'S WON FOR YOU". Action button "Cut Fighter" → "Release from
  Your Stable".

---

### 1.3 Progression

**Dashboard (4/10)**
- *Current:* Reputation + Fan Trust bars (voice phrases). Champions
  count "3 of 8". **But the cash sparkline is FAKE** — a hardcoded
  polyline in `dashboard.js` lines 187 (`points="0,20 20,18 40,16…"`)
  that always trends upward.
- *Missing:* No long-term growth visualization. No "promotion age".
  No "champions produced" or "homegrown stars count". No milestone
  timeline.
- *Recommendation:* Replace fake sparkline with real 90-day cash
  history (data already in `finance_svc`). Add three tiles:
  "PROMOTION AGE: 3y 4m", "CHAMPIONS PRODUCED: 7", "HOMEGROWN STARS:
  4". Add a milestone timeline strip at the bottom
  ("Apr 2026: First title · Jul 2026: First sold-out card · …").

**Roster (3/10)**
- *Current:* Weight class distribution bar chart (one snapshot). No
  trend. No roster-quality metric over time.
- *Missing:* No "your roster's average age dropped 2 years since
  January" — the kind of progression players remember.
- *Recommendation:* Add a **"Stable Quality Trend"** sparkline (last
  90 days, average fighter rating). Add "Average tenure: 2.3 years"
  + "Average age: 28 (was 31 in January)" callout.

**Free Agents (3/10)**
- *Current:* Nothing. Just a count of available fighters.
- *Missing:* No signing-budget context. No price comparison across
  tiers.
- *Recommendation:* Add a **"Your Signing Power"** indicator showing
  cash vs market: "You can afford 3 Elite-tier signings right now".
  Track over time: "Market prices are up 12% this quarter".

**Fighter Profile (6/10)**
- *Current:* Career stats tiles (record, win streak, loss streak,
  title reigns, career health, total fights). Title reigns card with
  reign-length chip. Fight history timeline.
- *Missing:* No trajectory sparkline. No "career peak" callout. No
  year-over-year form.
- *Recommendation:* Add a 12-fight form sparkline in the Career tab
  (W/L as bars). Surface "Career Peak: 2026" chip when fighter is at
  career-high momentum.

---

### 1.4 Emotional Attachment

**Dashboard (7/10)**
- *Current:* Fighter Watch uses momentum phrases ("scorching the
  earth on the way to a title shot") + pressure chips + form meter
  (last 5 results as colored blocks). Champion cards show reign
  length + defense count + multi-reign chip.
- *Missing:* No "first-ever champion" tag. No "last remaining
  original roster member". No comeback arcs surfaced.
- *Recommendation:* Add chips on champion cards: "FIRST EVER" (if
  inaugural champ of that WC), "LAST ORIGINAL" (if last fighter from
  roster inception). Add a **"Comeback Watch"** card to Fighter
  Watch for any fighter returning from 12+ month absence.

**Roster (4/10)**
- *Current:* Stage + Form voice phrases (italic) on every row. That's
  the extent.
- *Missing:* Fighters are rows, not people. No nickname-led "legends"
  view. No "homegrown" tag. No tenure.
- *Recommendation:* Add a "Homegrown" icon (gold star) for fighters
  who joined as prospects. Add a Tenure column ("5y" = 5 years with
  the player). Add a hover tooltip per row showing the fighter's
  most recent achievement ("Won L4 via KO/TKO at Event X").

**Free Agents (3/10)**
- *Current:* Stage short phrase + ceiling phrase. No backstories.
- *Missing:* Every fighter in the market is a row with no narrative.
- *Recommendation:* Add a 1-line narrative per scouted FA: "Released
  by Alpha Combat after losing 3 straight", "Career minor-leaguer
  finally getting a shot at 32", "Son of retired legend [Father
  Name]". This is exactly the kind of memory the Soul doc demands.

**Fighter Profile (8/10)** — best of the four screens.
- *Current:* Bio text, identity strip with 6 LONG voice phrases,
  nickname, champion crown, personality archetype chip, style chip,
  career-health chip. Fight history with opponent hyperlinks.
- *Missing:* No "memorable moments" pull-quotes (GPT's example: "Won
  8 straight before suffering a shocking upset"). No "career arc
  narrative" paragraph.
- *Recommendation:* Add a **"Memorable Moments"** card to the
  Overview tab: 2-3 generated phrases pulling from the fight history
  ("8-fight win streak snapped by [Opponent]", "First-ever KO
  finish", "Title won in front of [N] fans"). This is straight out
  of GPT's hook example.

---

### 1.5 Agency

**Dashboard (3/10)**
- *Current:* Almost zero callbacks to player decisions. Top Story is
  about the world; Recent News is about the world. The player's own
  past bookings/signings/cuts are not echoed.
- *Missing:* No "Since you signed X, he's won 4 straight". No "Your
  last cut signed with [Rival] and won their belt". No "Your
  decision to main-event [Fighter] drew the biggest gate of the
  year".
- *Recommendation:* Add an **"Echoes"** section (3 cards) between
  Top Story and Promotion Status:
  1. "Since you signed [Fighter] in [Month], he's won 4 straight."
  2. "[Fighter], who you released in [Month], just won [Rival]'s
     title."
  3. "Your decision to book [Fighter A] vs [Fighter B] at [Event]
     drew 12K fans — your biggest gate this year."
  Each card links to the relevant Fighter Profile or Past Event.

**Roster (3/10)**
- *Current:* No "you signed this fighter on date X" tag. No "your
  last booking of him was a win".
- *Missing:* Every row is context-free.
- *Recommendation:* Add a hover tooltip per row: "Signed: Mar 2026 ·
  Last fight: UD win vs [Opponent] · Next eligible: in 14 days".
  Surface this same information as a column on mobile / dense views.

**Free Agents (3/10)**
- *Current:* Fighters previously released by the player appear in the
  pool, but there's no tag indicating the connection.
- *Missing:* No "you released this fighter" framing.
- *Recommendation:* Tag released-by-you fighters with a **"CAME FROM
  YOUR STABLE"** chip. Add a 1-line context: "Since you cut him in
  [Month], he's won 2 of 3." This is GPT's exact example: "Released
  fighters may succeed elsewhere."

**Fighter Profile (5/10)**
- *Current:* Cut/Book/Scout/Sign action buttons are explicit calls
  to action. Opponent hyperlinks in fight history enable
  chain-of-curiosity.
- *Missing:* No "your history with this fighter" timeline. No "you
  signed him on [Date]" callout. No "he's 3-0 since you cut his last
  opponent".
- *Recommendation:* When the fighter is on the player's roster, add
  a **"Your History with [Fighter]"** section to the Overview tab:
  - "Signed: Mar 2026 (12-month contract, $X)"
  - "Record under you: 4-1"
  - "Biggest win: KO/TKO vs [Opponent] at [Event]"
  - "Contract expires in 87 days"
  Each line links to the relevant screen (Deals, Past Events, etc.).

---

## 2. The "Hook" Principle

> *"Every screen should contain at least one hook — a piece of
> information that makes the player want to click somewhere else."*
> — GPT

A hook = piece of information + link to another screen.

### 2.1 Dashboard — Hooks

**Current hooks (3):**
- Top Story → fighter profile (when `ts.fighter_id` is set)
- Recent News cards → fighter profile (when `n.fighter_id` is set)
- Fighter Watch name → Fighter Profile
- Champions name → Fighter Profile

**Current hook gaps:**
- Recent Results cards have **no click handler** — they're static
  display cards. (`dashboard.js` lines 340-353 — no `data-fighter-id`
  or `data-event-id`.)
- Next Event card has no click handler — should link to Event
  Builder / Matchmaking.
- Promotion Status tiles have no click handler — should link to
  Finance, Roster, Belts respectively.

**Hooks that SHOULD exist:**
| Hook | Interpretation layer data | Links to |
|---|---|---|
| "Rivalry brewing: A and B have exchanged words" | `rivalries_svc` heat ≥ 40 | Rivalries screen |
| "Your champion's contract expires in 27 days" | `contracts` expiration ≤ 30d | Deals screen |
| "Three of your welterweights are on 3-fight win streaks" | `win_streak ≥ 3` filtered by WC | Matchmaking |
| "Your last event drew 12K fans — biggest of the year" | `show_rating` historical | Past Events |
| "An unknown 19-year-old just hit the Open Market" | new FA age ≤ 21 | Free Agents |
| "Iron Forge Gym is producing unusual talent" | `training_svc` gym production streak | Training Camps |
| "Your rival promotion signed a top free agent" | `rival_ai.signing_agent` events | Rival Promotions |

### 2.2 Roster — Hooks

**Current hooks:** None explicit. Row click → Fighter Profile only.

**Hooks that SHOULD exist:**
| Hook | Data | Links to |
|---|---|---|
| "3 fighters are injured right now" | `injuries_svc` count | Roster filtered by injured |
| "Your longest-tenured fighter: 5 years" | signed_date oldest | Fighter Profile |
| "2 contracts expire within 30 days" | `contracts` expiry ≤ 30d | Deals |
| "4 fighters are on 3+ fight win streaks" | `win_streak ≥ 3` | Matchmaking (preselected) |
| "Your roster's average age dropped by 2 years since January" | roster age trend | Past Events (annual review) |
| "Iron Forge has 6 of your fighters" | gym roster count | Training Camps (that gym) |
| "Two of your champions haven't defended in 60+ days" | `titles.last_defense_date` | Matchmaking |

### 2.3 Free Agents — Hooks

**Current hooks:** Row click → Fighter Profile. No contextual hooks.

**Hooks that SHOULD exist:**
| Hook | Data | Links to |
|---|---|---|
| "An ex-champion hit the market today" | FA with `title_reigns ≥ 1` | Fighter Profile |
| "3 fighters from Alpha Combat released after rival event" | FA batch with same `previous_promo_id` | Past Events (that event) |
| "Your rival promotion is reportedly interested in X" | `rival_ai.signing_agent` intent log | Rival Promotions |
| "This 19-year-old reportedly has elite ceiling" | scouted FA `ceiling_scouted=True, ceiling='elite'` | Scouting report |
| "You can afford 5 Elite-tier signings right now" | `finance_svc.cash` vs avg cost | Finance |
| "A fighter you cut last month just signed elsewhere" | released-by-player FA signing news | Fighter Profile |
| "Three prospects from Mexico City hit the market this week" | FA region cluster | Scouting (that region) |

### 2.4 Fighter Profile — Hooks

**Current hooks:**
- Opponent hyperlinks in fight history → Fighter Profile (good — this
  is GPT's chain-of-curiosity pattern in action)
- Action buttons: Cut / Book / Scout / Sign (explicit calls to action)

**Current hook gaps:**
- No "rivals" callout — the player has to read the fight history
  manually to spot repeat opponents.
- No gym cross-reference — "trains at [Gym]" is just text, not a
  link.
- No contract-expiry hook when on player's roster.
- No "lost his last fight to your champion" cross-link.

**Hooks that SHOULD exist:**
| Hook | Data | Links to |
|---|---|---|
| "Won 8 straight before suffering a shocking upset" | fight history analysis | Scroll to that fight in timeline |
| "Three fights against [Opponent] — heat rising" | rivalry auto-detect (≥2 meetings) | Rivalries |
| "Trains at Iron Forge — 4 stablemates are also ranked" | gym roster + rankings | Training Camps |
| "Contract expires in 27 days" | `contracts` expiry | Deals |
| "Lost his last fight to your champion [Name]" | fight history vs player's champ | Fighter Profile (champ) |
| "Hometown: Mexico City — same as your signee [Name]" | `nationality` overlap | Roster (filtered) |
| "Was cut by [Rival Promo] in [Month]" | `previous_promo_id` history | Rival Promotions |

---

## 3. Reward Frequency — "Small Rewards" Firing on Advance Day

> *"The player should receive small rewards almost every in-game day."*
> — GPT

These are **interpretation-only** rewards — no new simulation. Each
fires when Advance Day produces a qualifying event, appears as a
one-line toast / news item / hook on the Dashboard, and links to the
relevant screen.

| # | Small Reward | Trigger data | Interpretation phrase | Links to |
|---|---|---|---|---|
| 1 | Prospect spotted | New fighter age ≤ 21 enters world seed / regen / academy | "A 19-year-old named [Name] is reportedly turning heads in [Region]." | Free Agents → Fighter Profile |
| 2 | Veteran announces comeback | `retirement_svc` flips retired → active after 12+ months out | "[Name], 4 years removed from his last fight, is reportedly training for a comeback." | Fighter Profile |
| 3 | Gym producing unusual talent | 2+ fighters from same gym reach `rising_contender` stage within 30 days | "[Gym Name] is on a tear — three of their fighters are climbing the ranks at once." | Training Camps |
| 4 | Champion decline | Champion's `momentum_label` drops from `high` → `falling` or `collapsing` | "[Name]'s reign is starting to feel the years. Three flat performances in a row." | Fighter Profile |
| 5 | Title picture becoming crowded | 3+ fighters in same WC reach `very_high` momentum | "The [WC] division is stacked — three legitimate contenders are all peaking at once." | Matchmaking or Rankings |
| 6 | Forgotten veteran resurgence | Fighter age ≥ 34, stage `declining`, wins 2 straight | "[Name], written off by everyone, has won two straight. Father time may have to wait." | Fighter Profile |
| 7 | Journalist questions matchmaking | Champion has gone 60+ days without a defense | "The press is asking why [Name] hasn't defended in two months." | Matchmaking or Deals |
| 8 | Released fighter succeeding elsewhere | Player-cut fighter signs with rival promo + wins debut | "[Name], who you released in [Month], won his debut for [Rival Promo] last night." | Fighter Profile (with Echoes section) |
| 9 | Rivalry escalating | `rivalries_svc` heat crosses 60 threshold | "Bad blood between [A] and [B] is boiling over — fans are demanding a third fight." | Rivalries |
| 10 | Comeback story completed | Fighter returning from 12+ month absence wins first fight back | "[Name] completed his comeback — [Method] in round [R]. The crowd erupted." | Fighter Profile / Fight Resolution |
| 11 | Homegrown star reaching contender | Player-roster fighter who joined as `prospect` reaches `rising_contender` or `champion` | "[Name], who you signed as a raw prospect, is now [Stage]. The investment is paying off." | Fighter Profile |
| 12 | Upset alert | Lower-ranked fighter (rating gap ≥ 15) defeats higher-ranked | "Stunning upset — [Underdog] just beat [Favorite] at [Event]." | Fight Resolution or Past Events |
| 13 | Regional talent wave | 3+ fighters from same region promoted to main card in 30 days | "[Region] is producing a wave of talent — three fighters debuted on main cards this month." | Scouting (that region) |
| 14 | Title defense milestone | Champion reaches 3 / 5 / 10 defenses | "[Name] notched his [N]th title defense — only [M] fighters in [Promo] history have done that." | Titles or Records |
| 15 | Contract expiring soon | Any player-roster fighter contract ≤ 30 days from expiry | "[Name]'s contract expires in [N] days. Time to talk extension." | Deals |

**Implementation note:** All 15 of these can be generated by the
existing interpretation layer (`src/interpretation/`) + the existing
event bus (`src/event_bus.py`) + the news engine
(`src/news.py`). No new simulation required — only new
*interpretation templates* and a small `player_decisions` log
(see §6 principle 4) to power #8, #11, #15.

---

## 4. Ownership Language — Specific Text Changes

> *"Replace neutral language with ownership language. Without changing
> data."* — GPT

### 4.1 Dashboard (`dashboard.js`)

| Current | Proposed |
|---|---|
| "Welcome back, Promoter." | "Your Empire awaits, Promoter." (or keep — already ownership-rich) |
| "THE EMPIRE" gradient header | "YOUR EMPIRE" |
| "PROMOTION STATUS" section | "YOUR PROMOTION'S HEALTH" |
| "CASH" stat tile | "YOUR WAR CHEST" |
| "REPUTATION" stat tile | "YOUR STANDING" |
| "FAN TRUST" stat tile | "THE FANS' TRUST IN YOU" |
| "ROSTER" stat tile | "YOUR ROSTER" |
| "CHAMPIONS" stat tile | "YOUR CHAMPIONS" |
| "3 of 8" champions display | "3 of 8 — five titles to capture" |
| "RECENT RESULTS" section | "CARDS YOU'VE RUN" |
| "RECENT NEWS" section | "WHAT THE WORLD SAYS ABOUT YOU" |
| "NEXT EVENT" section | "YOUR NEXT CARD" |
| "FIGHTER WATCH" section | "WHO'S MAKING MOVES FOR YOU" |
| "No champions yet. Win a title fight to claim a belt." | "No belts yet. The sport is yours for the taking." |
| "has X fighters, Y champions, and $Z in the bank." | "your roster sits at X, your champions at Y, your war chest at $Z." |

### 4.2 Roster (`roster.js`)

| Current | Proposed |
|---|---|
| "THE STABLE" (keep) | "THE STABLE" (already ownership-coded per GUI_PLAN §10.3) |
| "X fighters" subtitle | "X fighters under contract with you" |
| Column "Record" | "RECORD UNDER YOU" |
| Column "Gym" | "TRAINING WITH" |
| Column "Stage" | "WHERE HE IS" |
| Column "Form" | "RIGHT NOW" |
| "No fighters match your filters. Try clearing them." | "No one in your stable matches that. Try widening the lens." |
| "View Profile" button | "Open His Dossier" |

### 4.3 Free Agents (`free_agents.js`)

| Current | Proposed |
|---|---|
| "OPEN MARKET" (keep) | "OPEN MARKET" (already ownership-coded) |
| "X unsigned fighters" | "X fighters waiting for your call" |
| Modal title "SIGN FREE AGENT" | "BRING HIM INTO YOUR STABLE" |
| "Sign [Name] to your roster?" | "Bring [Name] into your stable?" |
| "The signing will be announced as news." | "Your signing will be announced as news." |
| "ESTIMATED COST" label | "WHAT HE'LL COST YOU" |
| "Sign for $X" button | "Sign for $X" (keep — already imperative) |
| "Confirm Signing" | "Make Him Yours" |
| "The market is quiet. Try clearing filters." | "The market is quiet. Your next star hasn't surfaced yet." |
| "Select a fighter to see signing cost." | "Pick someone to see what he'll cost you." |

### 4.4 Fighter Profile (`fighter_profile.js`)

| Current | Proposed (when on player's roster) |
|---|---|
| Header "[promo_name] · [gym_name]" | "Fights for YOUR promotion · Trains at [gym_name]" |
| Header meta "28y · Lightweight · orthodox stance" | "28 years old · Your Lightweight · orthodox stance" |
| Section "BIO" | "WHO HE IS" |
| Section "CAREER" | "HIS CAREER SO FAR" |
| Section "RECENT FIGHTS" | "WHAT HE'S DONE LATELY" |
| Section "FIGHTER ATTRIBUTES" | "WHAT HE BRINGS TO THE CAGE" |
| Section "PERSONALITY" | "WHO HE IS WHEN THE DOOR CLOSES" |
| Section "TITLE REIGNS" (if player-roster) | "BELTS HE'S WON FOR YOU" |
| Section "FIGHT HISTORY" | "THE FIGHTS THAT DEFINED HIM" |
| Section "NEWS" | "WHAT THEY'RE SAYING ABOUT HIM" |
| Stat tile "RECORD" | "RECORD UNDER YOUR PROMOTION" |
| Stat tile "WIN STREAK" | "CURRENT WIN STREAK" |
| Stat tile "LOSS STREAK" | "CURRENT LOSS STREAK" |
| Stat tile "TITLE REIGNS" | "BELTS HELD" |
| Stat tile "CAREER HEALTH" | "WHERE HIS BODY IS AT" |
| Stat tile "TOTAL FIGHTS" | "FIGHTS UNDER HIS BELT" |
| Action button "Cut Fighter" | "Release from Your Stable" |
| Action button "Book Next Fight" | "Book His Next Fight" |
| Action button "🔍 Scout" | "🔍 Send a Scout" |
| Action button "Sign to Roster" | "Bring Into Your Stable" |
| Cut confirm "Cut [name] from your roster?" | "Release [name] from your stable? He'll become a free agent." |
| "No biography on file." | "We don't have a read on him yet." |
| "No fights on record yet." | "He hasn't made his walk yet." |

---

## 5. Screen Review Checklist (GPT's 5 Questions)

### 5.1 Dashboard (The Empire)

1. **Discovery — Does this screen reveal something interesting?**
   *Partially.* Top Story + Recent News + Fighter Watch reveal
   emergent stories, but Recent Results cards are static (no
   click-through) and cross-promo activity is invisible. **Add:**
   "Across the Sport" section + make Recent Results clickable.

2. **Ownership — Does the wording reinforce that this is the
   player's organisation?**
   *Weakly.* "Welcome back, Promoter" and "YOUR CHAMPIONS" are good
   but stat tile labels ("CASH", "ROSTER") are neutral. **Fix:**
   Apply all §4.1 renames.

3. **Progression — Can the player clearly see long-term growth?**
   *Weakly.* Reputation + Fan Trust bars are present but the cash
   sparkline is fake. No promotion-age, no champions-produced count,
   no milestone timeline. **Add:** Real 90-day sparkline + 3 growth
   tiles + milestone strip.

4. **Attachment — Does this screen help players remember people
   instead of numbers?**
   *Mostly yes.* Fighter Watch momentum phrases + champion reign
   lengths do this well. **Enhance:** Add "FIRST EVER" / "LAST
   ORIGINAL" / "COMEBACK WATCH" tags to champion cards.

5. **Agency — Does the screen acknowledge previous player
   decisions?**
   *No.* Almost zero callbacks. **Add:** "Echoes" section with 3
   cards linking player decisions to current consequences. This is
   the highest-impact single change for the Dashboard.

### 5.2 Roster (The Stable)

1. **Discovery — Does this screen reveal something interesting?**
   *No.* Every fighter is already known to the player. **Add:**
   "Stable Pulse" banner with 2-3 generated hooks per §2.2.

2. **Ownership — Does the wording reinforce that this is the
   player's organisation?**
   *Weakly.* "THE STABLE" is good, but column headers are generic.
   **Fix:** Apply §4.2 renames + add a "Tenure" column.

3. **Progression — Can the player clearly see long-term growth?**
   *No.* Weight class distribution is a single snapshot. **Add:**
   Stable Quality Trend sparkline + average-age / average-tenure
   callouts.

4. **Attachment — Does this screen help players remember people
   instead of numbers?**
   *Partially.* Stage + Form voice phrases give texture, but
   fighters are rows. **Add:** "Homegrown" star icon + hover tooltip
   per row showing most recent achievement.

5. **Agency — Does the screen acknowledge previous player
   decisions?**
   *No.* **Add:** "Signed: [Date]" tooltip + "Last fight under you:
   [result]" + "Next eligible: [date]" per row.

### 5.3 Free Agents (Open Market)

1. **Discovery — Does this screen reveal something interesting?**
   *Partially.* Ceiling "?" creates scouting uncertainty, but no
   emergent narrative. **Add:** "Market Pulse" callout per §2.3 +
   1-line backstory per scouted FA.

2. **Ownership — Does the wording reinforce that this is the
   player's organisation?**
   *Weakly.* "OPEN MARKET" is good. **Fix:** Apply §4.3 renames +
   add "Suggested by Your Scouts" section.

3. **Progression — Can the player clearly see long-term growth?**
   *No.* **Add:** "Your Signing Power" indicator (cash vs avg cost)
   + market-price trend over time.

4. **Attachment — Does this screen help players remember people
   instead of numbers?**
   *No.* **Add:** 1-line narrative per scouted FA ("Released by
   Alpha Combat after losing 3 straight").

5. **Agency — Does the screen acknowledge previous player
   decisions?**
   *No.* **Add:** "CAME FROM YOUR STABLE" chip for fighters the
   player previously released, with 1-line context ("Since you cut
   him, he's won 2 of 3").

### 5.4 Fighter Profile

1. **Discovery — Does this screen reveal something interesting?**
   *Yes.* Identity strip with 6 voice phrases + fight history with
   opponent hyperlinks. **Enhance:** Add "Storylines" card with
   cross-screen hooks (rivals, gym stablemates, contract expiry).

2. **Ownership — Does the wording reinforce that this is the
   player's organisation?**
   *Weakly.* Promo line is neutral. **Fix:** Apply §4.4 renames for
   player-roster fighters (the most common case).

3. **Progression — Can the player clearly see long-term growth?**
   *Partially.* Career stats are static. **Add:** 12-fight form
   sparkline + "Career Peak: [Year]" chip.

4. **Attachment — Does this screen help players remember people
   instead of numbers?**
   *Strongly yes.* Best of the four screens. Bio + identity strip +
   nickname + champion crown + personality archetype. **Enhance:**
   Add "Memorable Moments" card (GPT's hook example: "Won 8 straight
   before suffering a shocking upset").

5. **Agency — Does the screen acknowledge previous player
   decisions?**
   *Partially.* Cut/Book/Scout actions are explicit, opponent links
   enable chain-of-curiosity. **Add:** "Your History with [Fighter]"
   section showing signed-date, record-under-you, biggest win,
   contract expiry — each line linking elsewhere.

---

## 6. Recommendations for Future Screens

GPT's principles should guide the design of the remaining **18
screens** (per GUI_PLAN §7.2: Schedule, News Feed, Scouting, Hall of
Fame, Event Builder, Matchmaking, Past Events, Finance, Contracts,
Rival Promotions, Gyms, Rankings, Titles, Rivalries, Records,
Settings, Save/Load, Mods).

The following **5 principles should be added to GUI_PLAN as
non-negotiable design rules** (proposed new §10.5 — "Reward Design
Laws"):

### Principle 1 — Every Screen Has at Least One Hook

Every screen must contain at least one piece of information that
links elsewhere. A "hook" = interpretation phrase + hyperlink to
another screen. Enforce in code review: if no `data-screen-target`
attribute exists anywhere on the rendered screen, the screen fails
review.

*Example:* The Contracts screen ("Deals") should not just list
contracts — it should include a hook like "3 of your champions have
contracts expiring within 60 days → view Matchmaking to plan
defenses". This pulls the player from Deals → Matchmaking.

### Principle 2 — Ownership Language Is the Default Register

Every section title, every stat label, every empty state uses "Your
X" / "Your Y" / "Your Z" framing. Neutral labels (e.g., "RECORD",
"CASH", "BIO") require an explicit waiver in the screen's design
doc. Apply §4 renames as the baseline; all future screens inherit
the same rule.

*Rationale:* GPT's directive — "Instead of 'Champion' consider 'Your
Lightweight Champion'." This is the cheapest, highest-impact reward
to deliver: zero new data, pure wording.

### Principle 3 — Every List View Has a "Pulse" Banner

Above every table (Roster, Free Agents, Past Events, Contracts,
Rankings, Rivalries, Records, Hall of Fame), include a 1-3 sentence
generated interpretation banner — the **"Pulse"** — that surfaces
what's *interesting* about that list right now: "3 fighters are
peaking", "2 contracts expire this month", "5 active rivalries are
heating up", etc.

*Implementation:* Generated by the interpretation layer from
existing data. One query, one template, no new systems.

### Principle 4 — Player Decisions Must Echo

When the player signs/cuts/books/releases a fighter, the system
must surface that fighter later with a callback. Add a small
**`player_decisions` log** (table or in-memory ring buffer) of the
last ~50 player decisions. The Dashboard's "Echoes" section and the
Fighter Profile's "Your History with [Fighter]" section both read
from this log. Without this, the Agency reward remains at 3/10
forever.

*Examples (per GPT):*
- Booking decisions should echo later ("Your main event of [Event]
  drew the biggest gate of the year").
- Signing decisions should be referenced later ("Since you signed
  him, he's won 4 straight").
- Released fighters may succeed elsewhere ("[Name], who you
  released, just won [Rival]'s title").

### Principle 5 — Numerical Progression Must Always Have a Story

No sparkline without a caption. No bar without a comparison. No
number without a trajectory. If cash is $50M, also show "up from
$32M last year" or "your best quarter ever". Data without narrative
context is forbidden.

*Rule:* Every numeric stat tile must have **(a)** a current value,
**(b)** a delta-or-comparison caption ("+12% vs last quarter" /
"your highest ever" / "lowest in 2 years"), and **(c)** a 30/90-day
sparkline where applicable. The Dashboard's current fake sparkline
is a direct violation of this principle and must be fixed.

---

## 7. Implementation Priority

If only **3 changes** can be made in the next sprint, in order:

1. **Replace the Dashboard's fake cash sparkline with real 90-day
   cash history** + add "Promotion Age" / "Champions Produced" /
   "Homegrown Stars" tiles. (Progression reward — currently 4/10.)
   Effort: ~4 hours (data already in `finance_svc`).

2. **Add "Echoes" section to Dashboard** + "Your History with
   [Fighter]" section to Fighter Profile, both reading from a new
   `player_decisions` log. (Agency reward — currently 3/10, the
   lowest score across all screens.) Effort: ~2 days (small schema
   addition for the log + interpretation templates).

3. **Apply all §4 ownership language renames** across the 4 screens.
   (Ownership reward — pure wording, zero data changes.) Effort:
   ~3 hours (string changes only).

These three changes alone would lift the Dashboard's average reward
score from 5.0 → ~7.0 and the Fighter Profile's from 6.2 → ~7.8,
without touching the simulation.

---

## 8. Cross-Reference

- **GPT directive:** `/home/z/my-project/upload/Cage GPT Revolution.txt`
- **Soul (5 fantasies):** `docs/CAGE_EMPIRE_SOUL.md`
- **GUI_PLAN voice/styling:** `docs/GUI_PLAN.md` §10 (lines 1035-1156)
- **Existing interpretation layer:** `src/interpretation/` —
  `memory_engine.py`, `career_phase_engine.py`, `narrative_families.py`,
  `context_engine.py`, `headline_engine.py`, `legacy_engine.py`
- **News engine:** `src/news.py` (already writes `news_engine` topic
  items — small rewards #1-#15 can be implemented as new headline
  templates here)
- **Event bus:** `src/event_bus.py` (subscribe to in-game events to
  trigger small rewards on Advance Day)
- **Screen renderers reviewed:** `src/web/js/dashboard.js` (449 lines),
  `src/web/js/roster.js` (390 lines), `src/web/js/free_agents.js`
  (563 lines), `src/web/js/fighter_profile.js` (650 lines)
