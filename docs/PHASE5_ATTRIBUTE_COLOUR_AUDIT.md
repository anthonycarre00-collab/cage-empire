# Phase 5 — Attribute Colour Scheme Audit

**Date:** 2026-08-17
**Task ID:** PHASE5-T4-ATTR-COLOUR
**Auditor:** Explore subagent

## Summary

- **Scheme location:** `src/web/js/fighter_profile.js:75-94` — the function is named **`phraseTier(phrase)`** (the task brief called it `attributeTier`, but the actual symbol in source is `phraseTier`). Tier→pct mapping is at `src/web/js/fighter_profile.js:563` inside `renderStatBar()`.
- **CSS classes:** `src/web/css/fighter_profile.css:495-497` (`.ce-fp-statbar-fill--gold`, `.ce-fp-statbar-fill--steel`, `.ce-fp-statbar-fill--crimson`) — uses double-dash BEM modifier syntax, NOT `.ce-stat-bar-fill-gold` as the task brief implied.
- **Tier→width→color mapping (verified end-to-end):**
  - `gold`    → `width: 100%` → `background: var(--gold)` `#e0a957` (theme.css:107)
  - `steel`   → `width: 60%`  → `background: var(--text-secondary)` `#aab0b8` (theme.css:100) — NOTE: steel tier uses the secondary-text gray variable, no dedicated `--steel` token.
  - `crimson` → `width: 25%`  → `background: var(--crimson)` `#d63a3f` (theme.css:106)
- **Schema reality check:** the task brief says "26 attribute_* columns" but the actual `fighter_descriptors` table has a SINGLE TEXT column `attribute_descriptors` holding a JSON dict of 26 keys (`punch_power`, `cardio`, …, `adaptability`). Same for `personality_descriptors` (20 keys). No `attribute_1` … `attribute_26` columns exist.
- **DB state:** 4,466 fighter_descriptors rows (brief says 4,450 — minor discrepancy, +16 rows likely from post-Phase-1 additions). 0 NULL, 0 empty dict, 0 malformed JSON.
- **Total distinct attribute phrases found in DB:** 445
- **Total distinct personality phrases found in DB:** 249
- **Attribute phrases correctly mapped to gold:** 25 distinct / 272 instances
- **Attribute phrases correctly mapped to crimson:** 46 distinct / 14,043 instances
- **Attribute phrases correctly mapped to steel:** 349 distinct / ~99,448 instances (370 in steel bucket − 18 look-elite − 3 look-weak)
- **Attribute phrases that fall through to 'steel' incorrectly:** **21 distinct / 1,215 instances** (LISTED below)
- **Attribute phrases mapped to 'gold' incorrectly (false positive):** **4 distinct / 1,450 instances** (LISTED below)
- **NULL/empty descriptor handling:** PASS — see §"Edge Cases"
- **All 26 attributes use `phraseTier()` consistently:** YES — see §"Consistency Check"

## Scheme Source Code (verbatim, for reference)

**`src/web/js/fighter_profile.js:75-94`** — the `phraseTier` function:
```js
  /** Map attribute phrase to a tier (gold/steel/crimson). */
  function phraseTier(phrase) {
    if (!phrase) return 'steel';
    var p = phrase.toLowerCase();
    // Elite-tier phrases → gold
    var eliteWords = ['elite', 'world-class', 'exceptional', 'lethal', 'master',
                      'devastating', 'top-tier', 'elite-level', 'powerful',
                      'explosive', 'iron', 'titanium', 'granite'];
    for (var i = 0; i < eliteWords.length; i++) {
      if (p.indexOf(eliteWords[i]) !== -1) return 'gold';
    }
    // Weak-tier phrases → crimson
    var weakWords = ['poor', 'weak', 'fragile', 'limited', 'vulnerable',
                     'soft', 'can be rocked', 'questionable', 'shaky',
                     'below-average', 'lacking'];
    for (var j = 0; j < weakWords.length; j++) {
      if (p.indexOf(weakWords[j]) !== -1) return 'crimson';
    }
    return 'steel';
  }
```

**`src/web/js/fighter_profile.js:558-583`** — the `renderStatBar` function (consumes `phraseTier`):
```js
  function renderStatBar(key, phrase, trajectory) {
    var tier = phraseTier(phrase);
    var label = humanize(key);
    // tier gold = 100%, steel = 60%, crimson = 25%
    var pct = tier === 'gold' ? 100 : tier === 'crimson' ? 25 : 60;
    // … (trajectory chip rendering — orthogonal to colour tier)
    return '' +
      '<div class="ce-fp-statbar">' +
        '<div class="ce-fp-statbar-label">' + escapeHtml(label) + '</div>' +
        '<div class="ce-fp-statbar-phrase">' + escapeHtml(phrase || '—') + chipHtml + '</div>' +
        '<div class="ce-fp-statbar-track"><div class="ce-fp-statbar-fill ce-fp-statbar-fill--' + tier + '" style="width:' + pct + '%"></div></div>' +
      '</div>';
  }
```

**`src/web/css/fighter_profile.css:485-497`** — CSS classes:
```css
.ce-fp-statbar-track {
  height: 6px;
  background: var(--border-subtle);
  border-radius: 0;
  overflow: hidden;
}
.ce-fp-statbar-fill {
  height: 100%;
  transition: width 0.3s ease;
}
.ce-fp-statbar-fill--gold     { background: var(--gold); }
.ce-fp-statbar-fill--steel    { background: var(--text-secondary); }
.ce-fp-statbar-fill--crimson  { background: var(--crimson); }
```

**CSS variable definitions** (`src/web/css/theme.css:100,106-107`):
```css
  --text-secondary: #aab0b8;   /* metadata, captions, table column headers */
  --crimson: #d63a3f;          /* loss, KO/TKO, danger, rival heat — IMPACT moments only */
  --gold: #e0a957;             /* EMPIRE wordmark, champion, primary actions, hyperlinks, win */
```

## Phrase Coverage Table

### False-positive GOLD (4 phrases — elite substring matched by accident)

| Phrase (as stored in DB) | DB count | Expected tier | Actual tier | Trigger word | Status |
|---|---:|---|---|---|---|
| `serviceable explosiveness` | 958 | steel | gold | `explosive` | ✗ FALSE POSITIVE — "serviceable" = average |
| `limited explosiveness` | 251 | crimson | gold | `explosive` | ✗ FALSE POSITIVE — "limited" = weak |
| `respectable explosiveness` | 228 | steel | gold | `explosive` | ✗ FALSE POSITIVE — "respectable" = decent/average |
| `lacks explosiveness` | 13 | crimson | gold | `explosive` | ✗ FALSE POSITIVE — "lacks" = absent/weak |

Net impact: 1,450 attribute instances across the DB are rendered as **gold (100% bar, gold color)** when they should be **steel (60% gray)** or **crimson (25% red)**.

### Missed GOLD (look-elite-but-currently-steel, 18 phrases — 903 instances)

| Phrase (as stored in DB) | DB count | Expected tier | Actual tier | Status |
|---|---:|---|---|---|
| `excellent takedowns` | 122 | gold | steel | ✗ |
| `excellent top control` | 100 | gold | steel | ✗ |
| `excellent cage work` | 94 | gold | steel | ✗ |
| `excellent scrambler` | 75 | gold | steel | ✗ |
| `excellent game planning` | 74 | gold | steel | ✗ |
| `dominant on top` | 74 | gold | steel | ✗ |
| `excellent bottom game` | 68 | gold | steel | ✗ |
| `excellent clinch defense` | 38 | gold | steel | ✗ |
| `excellent takedown defense` | 37 | gold | steel | ✗ |
| `excellent recovery` | 35 | gold | steel | ✗ |
| `excellent head movement` | 35 | gold | steel | ✗ |
| `excellent submission defense` | 30 | gold | steel | ✗ |
| `excellent chin` | 28 | gold | steel | ✗ |
| `excellent cardio` | 26 | gold | steel | ✗ |
| `unstoppable wrestling` | 24 | gold | steel | ✗ |
| `excellent clinch striking` | 16 | gold | steel | ✗ |
| `excellent footwork` | 16 | gold | steel | ✗ |
| `unstoppable in the clinch` | 11 | gold | steel | ✗ |

### Missed CRIMSON (look-weak-but-currently-steel, 3 phrases — 312 instances)

| Phrase (as stored in DB) | DB count | Expected tier | Actual tier | Status |
|---|---:|---|---|---|
| `lacks stopping power` | 284 | crimson | steel | ✗ |
| `helpless on the bottom` | 25 | crimson | steel | ✗ |
| `lacks physical strength` | 3 | crimson | steel | ✗ |

### Personality phrase — false-positive GOLD (1 phrase — 2 instances)

| Phrase (as stored in DB) | DB count | Expected tier | Actual tier | Trigger word | Status |
|---|---:|---|---|---|---|
| `can't adapt to new environments` | 2 | crimson or steel | gold | `iron` (substring of "envIRONments") | ✗ FALSE POSITIVE — "iron" is a substring of "environments" |

### Correctly mapped (sample — full list too long to include)

| Phrase | Expected tier | Actual tier | Status |
|---|---|---|---|
| `elite submission artist` | gold | gold | ✓ |
| `elite fight IQ` | gold | gold | ✓ |
| `master strategist` | gold | gold | ✓ |
| `powerful kicking game` | gold | gold | ✓ |
| `iron body` | gold | gold | ✓ |
| `iron chin` | gold | gold | ✓ |
| `devastating in the clinch` | gold | gold | ✓ |
| `devastating kicks` | gold | gold | ✓ |
| `explosive` | gold | gold | ✓ |
| `explosive athlete` | gold | gold | ✓ |
| `can be rocked by big shots` | crimson | crimson | ✓ |
| `below-average accuracy` | crimson | crimson | ✓ |
| `weak kicking game` | crimson | crimson | ✓ |
| `limited submissions` | crimson | crimson | ✓ |
| `poor cardio` | crimson | crimson | ✓ |
| `poor recovery` | crimson | crimson | ✓ |
| `fragile` | crimson | crimson | ✓ |
| `weak` | crimson | crimson | ✓ |
| `average cardio` | steel | steel | ✓ |
| `average chin` | steel | steel | ✓ |
| `serviceable durability` | steel | steel | ✓ |
| `holds his own` | steel | steel | ✓ |
| `knows the basics` | steel | steel | ✓ |
| `fades in deep waters` | steel | steel | ✓ |
| `recovers at a normal pace` | steel | steel | ✓ |
| `measured aggression` (personality) | steel | steel | ✓ |
| `respectable composure` (personality) | steel | steel | ✓ |
| `elite work ethic` (personality) | gold | gold | ✓ |
| `elite finisher` (personality) | gold | gold | ✓ |
| `below-average timing` (personality) | crimson | crimson | ✓ |
| `limited patience` (personality) | crimson | crimson | ✓ |
| `poor road fighter` (personality) | crimson | crimson | ✓ |

## Sample Fighter Render Verification

Sampled via SQL on `fighter_career` JOIN `fighters` JOIN `fighter_descriptors`. Note: `career_health` is heavily skewed to elite (90-100 bucket contains 3,247 of 4,466 = 73% of fighters). The "below-avg" / "weak" buckets had no exact matches on `career_health <= 49`, so they were approximated using `loss_streak >= 4` / `loss_streak >= 5` instead.

### Fighter 1 (ELITE): Harold Powell "The Tireless Complete" (id=1120)
- record: 12-8, health=100, streak=W5, title_reigns=0
- overall_desc: "Harold Powell 'The Tireless Complete' is a well-rounded fighter, with above-average on top and makes good adjustments, riding a five-fight win streak, currently journeyman."
- Attributes expected gold: 0 (none of his 26 phrases contain elite keywords legitimately)
- Attributes expected steel: 25 (well-rounded — phrases like "serviceable striking", "average accuracy", "respectable fight IQ")
- Attributes expected crimson: 0
- Attributes ACTUALLY rendered gold (via phraseTier): 1 → `speed_explosiveness` = "serviceable explosiveness" ← **FALSE POSITIVE** (should be steel; "explosive" substring match)
- Render trace for `speed_explosiveness`:
  1. API returns `attributes.speed_explosiveness = "serviceable explosiveness"` (app_web.py:4053)
  2. `renderAttributes()` line 488 puts it in `otherKeys` (not in `TOP_ATTRIBUTES` top-6).
  3. `renderStatBar('speed_explosiveness', 'serviceable explosiveness', traj)` called.
  4. `phraseTier('serviceable explosiveness')`: lowercases → loops eliteWords → matches `'explosive'` substring at index 12 → returns `'gold'`.
  5. `pct = 100` (line 563).
  6. HTML emitted: `<div class="ce-fp-statbar"><div class="ce-fp-statbar-label">Speed Explosiveness</div><div class="ce-fp-statbar-phrase">serviceable explosiveness</div><div class="ce-fp-statbar-track"><div class="ce-fp-statbar-fill ce-fp-statbar-fill--gold" style="width:100%"></div></div></div>`
  7. CSS rule `.ce-fp-statbar-fill--gold { background: var(--gold); }` paints it gold (#e0a957).
  8. **Net result:** 100%-width gold bar for a phrase that semantically means "average explosiveness". Incorrect — should be 60% gray bar.

### Fighter 2 (ABOVE-AVG): Kevin Richardson (id=3072)
- record: 14-11, health=80, streak=W7, title_reigns=0
- overall_desc: "Kevin Richardson is a grappler, with can win scrambles and respectable submissions, riding a seven-fight win streak, currently fallen contender."
- Attributes expected gold: 0
- Attributes expected steel: 21 (e.g., "lacks stopping power" *should* be crimson but maps to steel; "fades in deep waters"; "average fight IQ"; "wild at times"; "wild with his kicks")
- Attributes expected crimson: 5 → `chin` "can be rocked by big shots", `kick_power` "weak kicking game", `head_movement` "below-average head movement", `clinch_striking` "weak in the clinch", `speed_explosiveness` "below-average speed"
- Attributes ACTUALLY rendered gold (via phraseTier): 0
- Render trace for `punch_power` "lacks stopping power":
  1. `phraseTier('lacks stopping power')`: loops eliteWords — no match. Loops weakWords — no match (no "poor"/"weak"/"limited"/"below-average"/"lacking" substring). Falls through → `'steel'`.
  2. `pct = 60` → 60% gray bar.
  3. **Net result:** 60% gray bar for a phrase that semantically means "weak striking power". Should be 25% crimson. Missed mapping.

### Fighter 3 (AVG): Steven Chavez "The Fading Millstone" (id=235)
- record: 21-18, health=60, streak=W5
- overall_desc: "Steven Chavez 'The Fading Millstone' is a wrestler, with above-average wrestling and respectable cage wrestling, riding a five-fight win streak, currently grizzled veteran."
- Attributes expected gold: 0
- Attributes expected steel: 25 (e.g., "won't shock anyone with his hands", "fades in deep waters", "follows a game plan", "average chin", "struggles to find the target")
- Attributes expected crimson: 1 → `bottom_game` "limited bottom game"
- Attributes ACTUALLY rendered gold (via phraseTier): 0
- Render trace for `bottom_game` "limited bottom game":
  1. `phraseTier('limited bottom game')`: loops eliteWords — no match. Loops weakWords → matches `'limited'` at index 0 → returns `'crimson'`.
  2. `pct = 25` → 25% crimson bar.
  3. **Net result:** 25% red bar. CORRECT.

### Fighter 4 (BELOW-AVG): Viktor Petrov "The Thunder Smesh" (id=2985)
- record: 30-46, health=60, streak=W8/L5 (anomalous — long-term loser on a recent winning streak)
- overall_desc: "Viktor Petrov 'The Thunder Smesh' is a wrestler, with can take down most fighters and above-average against the fence, riding a eight-fight win streak, currently wily veteran."
- Attributes expected gold: 0
- Attributes expected steel: 24 (e.g., "serviceable striking", "serviceable stamina", "above-average awareness", "average accuracy", "serviceable kicks")
- Attributes expected crimson: 1 → `chin` "can be rocked by big shots"
- Attributes ACTUALLY rendered gold (via phraseTier): 1 → `speed_explosiveness` "serviceable explosiveness" ← **FALSE POSITIVE** (should be steel)
- Render trace for `speed_explosiveness`: same as Fighter 1 — false positive gold bar at 100%.
- Render trace for `chin` "can be rocked by big shots":
  1. `phraseTier(...)`: loops eliteWords — no match. Loops weakWords → matches `'can be rocked'` at index 0 → returns `'crimson'`.
  2. `pct = 25` → 25% crimson bar. CORRECT.

### Fighter 5 (WEAK): Adam Roberts "The Reliable All-Rounder" (id=91)
- record: 10-10, health=100, streak=W0/L6 (on a six-fight skid)
- overall_desc: "Adam Roberts 'The Reliable All-Rounder' is a well-rounded fighter, with can change plans and average scrambler, on a six-fight skid, currently fallen contender."
- Attributes expected gold: 0
- Attributes expected steel: 24 (e.g., "average power", "fades in deep waters", "average fight IQ", "serviceable timing", "average kicking power")
- Attributes expected crimson: 2 → `chin` "can be rocked by big shots", `strength` "limited strength"
- Attributes ACTUALLY rendered gold (via phraseTier): 0
- Render trace for `strength` "limited strength":
  1. `phraseTier('limited strength')`: matches `'limited'` → `'crimson'`.
  2. `pct = 25` → 25% crimson bar. CORRECT.

## Consistency Check

- **All 26 attributes use `phraseTier()`: YES**
  - `renderAttributes()` at `src/web/js/fighter_profile.js:481-518` iterates ALL keys in the `attributes` dict (the API returns all 26 keys, never a subset) and calls `renderStatBar(k, attrs[k], traj[k])` for each (lines 494, 495).
  - `renderStatBar()` at line 558 calls `phraseTier(phrase)` at line 559 unconditionally — no per-key special-casing.
- **All 20 personality traits use `phraseTier()`: YES**
  - `renderPersonality()` at lines 521-556 calls `renderStatBar(k, pers[k], null)` for each personality key (lines 532, 533) — same path.
- **Exceptions (attributes with custom color logic): 1, NOT one of the 26 attributes:**
  - `src/web/js/fighter_profile.js:307` — the **Career Health** stat tile on the Overview tab uses a DIFFERENT class pattern: `ce-stat-bar-fill ce-stat-bar-gold` (note the SINGLE dash, not BEM double-dash). This is the `career_health` numeric metric (0-100 int from `fighter_career.career_health`), NOT a voice phrase. It uses `width: <pct>%` from the numeric value (Math.max(0, Math.min(100, cs.career_health))). This is the CORRECT behavior — career_health is a derived health number, not a voice phrase, so it should bypass the phrase-tier scheme. CSS class `ce-stat-bar-gold` is not defined in `fighter_profile.css` (only `.ce-fp-stat-tile .ce-stat-bar { margin-top: 2px; }` at line 353) — it must be inherited from a generic stylesheet (likely `components.css` or `theme.css`); a small cosmetic inconsistency but out of scope for this audit.
- **No other inline color logic for attribute bars exists.** Verified via grep: the only `phraseTier()`-derived tier tokens (`gold`/`steel`/`crimson`) appear inside `renderStatBar()` (lines 559, 563, 581).

## Edge Cases

### NULL descriptor handling: PASS
- `phraseTier()` line 77: `if (!phrase) return 'steel';` — null/undefined/empty-string all coerce to `steel` tier → 60% gray bar. Verified in code.
- `renderStatBar()` line 580: `escapeHtml(phrase || '—')` — when phrase is falsy, the displayed phrase text is an em-dash `—` (no missing-text gap). Verified in code.
- `renderAttributes()` line 487: `TOP_ATTRIBUTES.filter(function (k) { return attrs[k]; });` — filters out empty/null attribute values from the top-6 list (so an empty phrase doesn't get a mislabeled gold/steel bar). Verified in code.
- `renderAttributes()` line 488: `keys.filter(function (k) { return TOP_ATTRIBUTES.indexOf(k) === -1; });` — uses the FULL key list (no attrs[k] filter on `otherKeys`), so an empty phrase WILL still render via `renderStatBar` with em-dash + 60% bar. Verified in code.
- DB reality: 0 NULL `attribute_descriptors` rows, 0 empty JSON dicts. The null-handling code path is dead in the current DB but is correctly implemented as defensive code.

### Empty string descriptor handling: PASS
- Same path as NULL (empty string is falsy, returns `'steel'`, displays `—`). Verified.

### Unknown phrase (not in eliteWords/weakWords) handling: PARTIAL PASS
- The fall-through to `'steel'` is intentional and explicit (line 93: `return 'steel';`). Verified.
- HOWEVER, the substring matching is too loose:
  - **"explosive"** matches as a SUBSTRING inside any phrase that contains those exact characters, including phrases where the prefix modifier ("limited", "serviceable", "respectable", "lacks") inverts the meaning. This produces 4 false-positive GOLD phrases (1,450 instances in the DB).
  - **"iron"** matches as a SUBSTRING inside "envIRONments" — 1 personality phrase (2 instances) is mislabeled GOLD when it should be CRIMSON ("can't adapt to new environments").
- AND the elite/weak word lists are missing common synonyms:
  - **"excellent"** (16 distinct phrases, ~891 instances) — clearly elite-intent, falls through to steel.
  - **"dominant"** (1 phrase, 74 instances) — clearly elite-intent, falls through to steel.
  - **"unstoppable"** (2 phrases, 35 instances) — clearly elite-intent, falls through to steel.
  - **"lacks"** (2 distinct phrases, 287 instances — "lacks stopping power" + "lacks physical strength") — clearly weak-intent, falls through to steel.
  - **"helpless"** (1 phrase, 25 instances) — clearly weak-intent, falls through to steel.
- Net effect: **26 distinct phrases / 2,665 attribute instances** (out of 445 phrases / 116,116 instances = ~2.3% of all attribute renderings) are mis-tiered.

## Recommendations

If a follow-up task is opened to fix the issues found here, these are the recommended additions. **No code changes made in this audit** — listed for follow-up planning only.

**Add to `eliteWords` (to catch missed elite phrases):**
- `"excellent"` — would catch 16 distinct phrases / ~891 instances currently mis-rendered as steel
- `"dominant"` — would catch "dominant on top" (74 instances)
- `"unstoppable"` — would catch 2 phrases / 35 instances

**Add to `weakWords` (to catch missed weak phrases):**
- `"lacks"` — would catch "lacks stopping power" (284) + "lacks explosiveness" (13) + "lacks physical strength" (3) = 300 instances
  - **Note:** this would ALSO correctly re-bucket "lacks explosiveness" from false-positive gold → crimson, fixing the substring bug for that phrase.
- `"helpless"` — would catch "helpless on the bottom" (25 instances)

**Substring false-positive mitigations (the harder problem — requires more than just adding words):**
- `"serviceable explosiveness"` (958 instances) — contains elite word `"explosive"` but semantically means average. Adding `"serviceable"` to `weakWords` would NOT fix this (elite check runs FIRST and wins). Possible fixes (out of scope for this audit):
  1. Reorder the tier checks: check `weakWords` FIRST, then `eliteWords`. Would correctly handle "limited explosiveness" + "lacks explosiveness" → crimson. But would mis-bucket legitimate phrases containing both a weak word AND an elite word (rare in practice — current DB has none).
  2. Use word-boundary regex matching instead of `indexOf` substring (e.g., `/\bexplosive\b/` instead of `p.indexOf('explosive') !== -1`). This would NOT fix "serviceable explosiveness" (the word "explosive" is still there as a complete word) but would fix "environments" → "iron" (envIRONments has no word boundary around "iron").
  3. Maintain a stoplist of "qualifier words" ("serviceable", "respectable", "decent", "average", "limited", "lacks", "poor") and skip the elite match if any qualifier precedes the elite word.
- `"can't adapt to new environments"` (2 instances) — `"iron"` substring of `"environments"`. Word-boundary regex (`/\biron\b/`) would fix this.

**For the personality tier bug:**
- Same word-boundary regex fix would correct "environments" → no longer matches "iron".

## Files Audited

- `src/web/js/fighter_profile.js` (970 lines, total)
  - `phraseTier()` function — lines 75-94
  - `renderStatBar()` function — lines 558-583
  - `renderAttributes()` function — lines 481-518 (consumer of renderStatBar)
  - `renderPersonality()` function — lines 521-556 (consumer of renderStatBar)
  - Career Health stat tile (Overview tab, NOT one of 26 attributes) — line 307
- `src/web/css/fighter_profile.css` (648 lines, total)
  - `.ce-fp-statbar-track` — line 485
  - `.ce-fp-statbar-fill` — line 491
  - `.ce-fp-statbar-fill--gold` — line 495
  - `.ce-fp-statbar-fill--steel` — line 496
  - `.ce-fp-statbar-fill--crimson` — line 497
- `src/web/css/theme.css` — `--gold`, `--crimson`, `--text-secondary` variable definitions at lines 100, 106, 107.
- `src/app_web.py` — `get_fighter_profile_data` API method at line 3610; reads `attribute_descriptors` JSON at line 3743, returns it as `attributes` at line 4053.
- `data/cage_empire.db` — `fighter_descriptors` table:
  - 4,466 active fighter rows (0 NULL, 0 empty, 0 malformed)
  - 26 distinct attribute keys per row
  - 20 distinct personality keys per row
  - 445 distinct attribute phrases across all rows
  - 249 distinct personality phrases across all rows
  - 116,116 total attribute instances
  - 89,320 total personality instances

## NO Code Changes Made

This was a read-only audit. No files were modified. The only file created is this audit report (`docs/PHASE5_ATTRIBUTE_COLOUR_AUDIT.md`).
