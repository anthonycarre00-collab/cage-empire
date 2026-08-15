> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Change Requests CR-5..9 (User Feedback Round 2)

> **Status:** ACTIVE — planning + implementation tracker for the 5
> change requests raised after testing CR-1..4.
> **Source:** user feedback in IM chat 2026-08-03 (round 2).
> **Supervisor:** main agent. Two parallel subagents will implement.
> **Source of truth for:** Dashboard live-data fixes, Roster promo
> logo + gender toggle, Fighter Profile label simplification, Rival
> Promotions screen (new).

---

## 0. Summary of user feedback

> "Empire" screen — check the "who's making moves" section is pulling
> live relevant data and limit "cards you've run" to past 3 shows
> because it runs off the page. "Stable" screen needs the relevant
> promotion logo near the top. "Fighter profile" screen now has
> current promotion instead of "your promotion" but ensure this
> field updates if fighter leaves or signs with a different promotion
> and under career sub tab change "Belts he's won for you" to just
> "Belts won" *ensure gender separation/calls for he/she. "Stable"
> screen weight distribution section should have a male/female toggle
> rather than showing all, default to male fighter distribution. Q.
> i am playing as "rival fight league", how can i see the
> rosters/contracted fighters at other promotions? Consider my
> points and apply updates/fixes then continue with next phases
> acting as supervisor again and signing off
> completeness/wiring/voice/design/reward/fantasy/performance etc.

Five discrete change requests:

| # | Title | Files touched | Subagent |
|---|---|---|---|
| CR-5 | Dashboard "Who's Making Moves" — filter to player's promo | app_web.py, dashboard.js | C (dashboard) |
| CR-6 | Dashboard "Cards You've Run" — limit to 3 + filter to player's promo | app_web.py, dashboard.js | C (dashboard) |
| CR-7 | Roster — promo logo near top + weight distribution gender toggle | roster.js, app_web.py, roster.css | D (roster) |
| CR-8 | Fighter Profile Career tab — "BELTS HE'S WON FOR YOU" → "BELTS WON" | fighter_profile.js | D (fighter_profile) |
| CR-9 | NEW: "The Competition" screen — rival promotions list + view rival roster | app.js, rival_promotions.js (new), rival_promotions.css (new), app_web.py | D (new screen) |

### Already verified working (NO change needed)

**Fighter promotion field updates dynamically** — `get_fighter_profile_data` reads `fighters.current_promotion_id` via a JOIN (app_web.py:1642: `promo_name = promo_row[0] if promo_row else "Free Agent"`). When a fighter signs with a different promo or gets cut, `current_promotion_id` is updated by `sign_free_agent` / `cut_fighter`, and the next profile load reflects the new promo. Verified with 3 test cases (player-roster, free agent, rival promo). **No code change needed** — this already works.

---

## 1. CR-5 — Dashboard "Who's Making Moves" — filter to player's promo

### 1.1 Problem
The "WHO'S MAKING MOVES FOR YOU" section (dashboard.js:301, 344) pulls from `fighter_watch` data (app_web.py:832-895). The current logic:
- `fastest_rising` + `biggest_fall` query `daily_headlines` (no promo filter)
- `HOTTEST STREAK` queries `fighter_descriptors` WHERE `momentum LIKE 'very_high||%'` AND `is_active=1` (no promo filter)

So the section can surface fighters from RIVAL promotions — not "for you" as the title claims.

### 1.2 Fix
Add `AND f.current_promotion_id=?` to ALL three watch queries in `get_dashboard_data` (app_web.py:844-854). Pass `pid` (the player's promo).

**Backend changes (app_web.py:832-895):**
- Line 844 (`HOTTEST STREAK`): add `AND f.current_promotion_id=?` + pass `(pid,)` instead of no param.
- Line 852-854 (`fastest_rising` + `biggest_fall`): the `daily_headlines` query returns a `fighter_id`. After fetching it, verify the fighter is on the player's promo. If not, skip (don't show a rival's prospect as "TOP PROSPECT FOR YOU"). Add a JOIN or subquery:
  ```sql
  SELECT dh.fighter_id FROM daily_headlines dh
  JOIN fighters f ON f.fighter_id = dh.fighter_id
  WHERE dh.headline_type=? AND f.current_promotion_id=? AND f.is_active=1
  ORDER BY dh.headline_date DESC LIMIT 1
  ```

### 1.3 Acceptance criteria
- [ ] All 3 fighter watch cards show only fighters on the player's promo
- [ ] If no fighters qualify (e.g., player has 0 prospects), the section shows a graceful empty state, not rival fighters
- [ ] The section title remains "WHO'S MAKING MOVES FOR YOU"
- [ ] No regression: clicking a watch card still navigates to Fighter Profile

---

## 2. CR-6 — Dashboard "Cards You've Run" — limit to 3 + filter to player's promo

### 2.1 Problem
The "CARDS YOU'VE RUN" section (dashboard.js:382-411) renders `d.recent_results` (app_web.py:924-936). The current query:
```sql
SELECT p.name, e.event_date, e.event_name, sr.overall_rating, sr.rating_description
FROM events e JOIN promotions p ON p.promotion_id=e.promotion_id
LEFT JOIN show_ratings sr ON sr.event_id=e.event_id
WHERE e.status='completed' ORDER BY e.event_date DESC LIMIT 4
```
Two issues:
1. **No promo filter** — shows ANY promo's completed events, not just the player's. The section title "CARDS YOU'VE RUN" implies player-owned events only.
2. **LIMIT 4** — user wants LIMIT 3 (it runs off the page).

### 2.2 Fix
**Backend (app_web.py:925-929):**
```sql
SELECT p.name, e.event_date, e.event_name, sr.overall_rating, sr.rating_description
FROM events e JOIN promotions p ON p.promotion_id=e.promotion_id
LEFT JOIN show_ratings sr ON sr.event_id=e.event_id
WHERE e.status='completed' AND e.promotion_id=?
ORDER BY e.event_date DESC LIMIT 3
```
Pass `(pid,)`.

### 2.3 Acceptance criteria
- [ ] Only the player's promo's completed events appear
- [ ] Maximum 3 cards shown (was 4)
- [ ] If player has 0 completed events, shows the existing empty state ("No cards in the archive yet...")
- [ ] Cards still display promo name, event name, date, rating

---

## 3. CR-7 — Roster promo logo + weight distribution gender toggle

### 3.1 Promo logo near the top

**File:** `src/web/js/roster.js` — `render(data)` function (line 245-265).

The roster payload from `get_roster_data` does NOT currently include the promo logo. Add it.

**Backend (app_web.py `get_roster_data`):**
- Add `"promo_logo_b64": _load_logo_b64(pid)` to the return dict (line 984-993). `_load_logo_b64` is already defined (used by dashboard + pre-game).

**Frontend (roster.js:249-261):**
- Add a logo `<img>` to the section header, before "THE STABLE" title:
  ```js
  var logoHtml = data.promo_logo_b64
    ? '<img src="data:image/png;base64,' + data.promo_logo_b64 + '" class="ce-roster-promo-logo" alt="' + escapeHtml(data.promo_name || '') + '" />'
    : '';
  // ...
  '<div class="ce-sec-header">' +
    logoHtml +
    '<div class="ce-accent-bar ce-accent-gold"></div>' +
    '<span class="ce-sec-title ce-sec-title-gold">THE STABLE</span>' +
    '<span class="ce-sec-sub ce-mono">' + (data.total || 0) + ' fighters under contract with you</span>' +
  '</div>' +
  ```
- Also need `promo_name` in the payload (add to backend return dict).

**CSS (roster.css):**
- `.ce-roster-promo-logo` — 40×40px, rounded, gold border, margin-right 12px, vertical-align middle.

### 3.2 Weight distribution gender toggle

**File:** `src/web/js/roster.js` — `renderWeightClassViz(data)` (line 225-243).

Currently shows ALL weight classes (men + women) in one flat list. Add a male/female toggle, default to male.

**Implementation:**
- Add `state.wcVizGender: 'male'` to roster state (default male).
- Modify `renderWeightClassViz` to:
  1. Filter `data.weight_classes` by `state.wcVizGender`.
  2. Render a toggle: `[Men's] [Women's]` (two buttons, active state highlighted).
  3. Render only the filtered weight classes in the bar viz.
- Wire toggle click → update `state.wcVizGender` → re-render just the viz section (not the whole screen).

**Toggle HTML:**
```html
<div class="ce-wc-viz-toggle">
  <button class="ce-wc-toggle-btn ce-wc-toggle-btn--active" data-gender="male">Men's</button>
  <button class="ce-wc-toggle-btn" data-gender="female">Women's</button>
</div>
```

**CSS:**
- `.ce-wc-viz-toggle` — inline-flex, gap 4px, margin-bottom 12px.
- `.ce-wc-toggle-btn` — small button, dark bg, gray text.
- `.ce-wc-toggle-btn--active` — gold bg, dark text.

### 3.3 Acceptance criteria
- [ ] Promo logo appears in the roster header (left of "THE STABLE" title)
- [ ] Weight distribution shows a Men's / Women's toggle
- [ ] Default view shows Men's weight classes only
- [ ] Clicking Women's shows only Women's weight classes
- [ ] Toggle doesn't re-render the whole screen (just the viz section)
- [ ] If a gender has 0 fighters, shows empty state for that gender

---

## 4. CR-8 — Fighter Profile Career tab label simplification

### 4.1 Problem
Career tab (fighter_profile.js:573): `LBL_TITLE_REIGNS = onRoster ? ('BELTS ' + p.hes + ' WON FOR YOU') : 'TITLE REIGNS';`

This renders as "BELTS HE'S WON FOR YOU" / "BELTS SHE'S WON FOR YOU". User wants it simplified to just "BELTS WON" — gender-neutral, simpler.

### 4.2 Fix
**File:** `src/web/js/fighter_profile.js:573`.

Change to:
```js
var LBL_TITLE_REIGNS = onRoster ? 'BELTS WON' : 'TITLE REIGNS';
```

"BELTS WON" is already gender-neutral (no pronoun). The `p` pronouns helper is still used for OTHER labels in the same function (LBL_FIGHT_HISTORY = "THE FIGHTS THAT DEFINED HIM/HER"), so gender separation is preserved elsewhere.

### 4.3 Acceptance criteria
- [ ] Career tab section title shows "BELTS WON" (not "BELTS HE'S WON FOR YOU")
- [ ] Other section titles in the Career tab still use gendered pronouns ("THE FIGHTS THAT DEFINED HIM/HER")
- [ ] Non-roster fighters still see "TITLE REIGNS"

---

## 5. CR-9 — NEW: "The Competition" screen (rival promotions + view rival roster)

### 5.1 Problem (user's Q)
User plays as "Rival Fight League" (promo 2). They asked: "How can I see the rosters/contracted fighters at other promotions?"

Currently, the "rival_promotions" nav item (app.js:50) is a placeholder. The player has NO way to see rival promo rosters.

### 5.2 Design

Build a new screen "The Competition" that:
1. Lists all rival promotions (9 of them, excluding the player's own).
2. Each card shows: promo logo, name, size_tier, broadcast_tier, roster count, champion count, cash (optional — could be hidden for rivals as "intelligence gap"), reputation phrase.
3. Clicking a promo card → drills into that promo's roster (read-only — same table as the player's Roster screen, but filtered to the rival promo, with no Sign/Cut/Book actions).
4. Fighter name hyperlinks in the rival roster → Fighter Profile (read-only — no action buttons for Cut/Book, but Scout/Sign-to-Roster still available if the fighter is a free agent approaching expiry).

### 5.3 Implementation

**New files:**
- `src/web/js/rival_promotions.js` — new screen renderer.
- `src/web/css/rival_promotions.css` — styles.

**Modified files:**
- `src/web/index.html` — add `<script>` + `<link>` tags for the new files.
- `src/web/js/app.js` — add `rival_promotions` to the nav config (already there at line 50) + wire the navigate handler to call the new renderer.
- `src/app_web.py` — add 2 new API methods:
  - `get_rival_promotions()` — returns list of rival promos with summary stats.
  - `get_rival_roster(promo_id, page, filters)` — returns rival promo's roster (read-only, same shape as `get_roster_data` but for a non-player promo).

**Backend (app_web.py):**

`get_rival_promotions()`:
```python
def get_rival_promotions(self):
    """Return list of rival promotions (excluding player's own)."""
    pid = self.get_player_promotion()
    rows = self.conn.execute("""
        SELECT p.promotion_id, p.name, p.size_tier, p.broadcast_tier,
               p.reputation, p.fan_trust, p.current_cash,
               (SELECT COUNT(*) FROM fighters f WHERE f.current_promotion_id=p.promotion_id AND f.is_active=1) as roster_count,
               (SELECT COUNT(*) FROM titles t WHERE t.promotion_id=p.promotion_id AND t.is_vacant=0) as champ_count
        FROM promotions p
        WHERE p.promotion_id != ?
        ORDER BY p.size_tier DESC, p.reputation DESC
    """, (pid,)).fetchall()
    return [{
        "promotion_id": r[0],
        "name": r[1],
        "size_tier": (r[2] or "").upper(),
        "broadcast_tier": (r[3] or "").upper(),
        "reputation": r[4] or 0,
        "reputation_phrase": _reputation_phrase(r[4] or 0),
        "fan_trust": r[5] or 0,
        "fan_trust_phrase": _fan_trust_phrase(r[5] or 0),
        "current_cash": float(r[6] or 0),
        "roster_count": r[7],
        "champ_count": r[8],
        "logo_b64": _load_logo_b64(r[0]),
    } for r in rows]
```

`get_rival_roster(promo_id, page, filters)`:
- Mirror `get_roster_data` but for a non-player promo.
- Same filters (wc, gender, stage, search, sort_col, sort_dir).
- Same pagination (20/page).
- Same column shape (fighter_id, name, nickname, age, wc_name, stage_short, form_short, record_str, gym_name, nat_code).
- NO sign/cut/book actions exposed (those are player-only).

**Frontend (rival_promotions.js):**

Two views in one screen:
1. **Promo list view** (default): grid of rival promo cards. Each card:
   - Logo (base64)
   - Name (large)
   - Size tier + broadcast tier chips
   - Reputation phrase + fan trust phrase (voice phrases, not raw numbers)
   - Roster count + champion count
   - "View Roster" button → switches to roster view
2. **Roster view** (when a promo is selected): same table as Roster screen, but:
   - Header shows "VIEWING: [Promo Name]" + back button
   - No Sign/Cut/Book actions
   - Fighter name hyperlinks → Fighter Profile
   - Filters work (wc, gender, stage, search, sort)
   - Pagination works

**State:**
```js
var state = {
  view: 'list',  // 'list' or 'roster'
  selectedPromoId: null,
  page: 1,
  filters: { wc: '0', gender: 'all', stage: 'all', search: '', sort_col: 'name', sort_dir: 'asc' },
  weightClasses: [],
  _searchTimer: null,
};
```

### 5.4 Acceptance criteria
- [ ] Clicking "The Competition" in sidebar → shows promo list
- [ ] All 9 rival promos appear as cards (excluding player's own)
- [ ] Each card shows logo, name, tiers, reputation phrase, roster count, champ count
- [ ] Clicking "View Roster" on a card → shows that promo's roster
- [ ] Roster view has a back button → returns to promo list
- [ ] Roster view supports filters (wc, gender, stage, search, sort)
- [ ] Fighter name hyperlinks → Fighter Profile
- [ ] NO Sign/Cut/Book action buttons on rival roster (read-only)
- [ ] If a rival fighter is a free agent approaching contract expiry, the Sign button IS available (player can poach) — but this is a Phase E3 feature, so for now just hide all actions
- [ ] Performance: list view renders in <50ms, roster view reuses the roster.js table renderer pattern

### 5.5 Voice + design notes
- Section header for list view: "THE COMPETITION" with gold accent bar + subtitle "9 promotions vying for the same talent, the same fans, the same belts."
- Each promo card uses the same visual pattern as the pre-game promo cards (logo + name + meta chips).
- Roster view header: "VIEWING: [PROMO NAME]" + "(read-only)" small text + back button.
- Empty state if a rival promo has 0 fighters: "Their stable is empty. Looks like an opportunity."

---

## 6. Subagent assignments

### Subagent C — Dashboard (CR-5 + CR-6)
**Task ID:** CR-C-DASHBOARD
**Files owned:** `src/web/js/dashboard.js`, `src/app_web.py` (only `get_dashboard_data` method, lines 746-989).
**Scope:**
- CR-5: filter fighter_watch queries to player's promo
- CR-6: filter recent_results to player's promo + LIMIT 3

### Subagent D — Roster + Fighter Profile + New Screen (CR-7 + CR-8 + CR-9)
**Task ID:** CR-D-ROSTER-FP-COMPETITION
**Files owned:** `src/web/js/roster.js`, `src/web/css/roster.css`, `src/web/js/fighter_profile.js` (only Career tab label), `src/web/js/rival_promotions.js` (NEW), `src/web/css/rival_promotions.css` (NEW), `src/web/index.html`, `src/web/js/app.js` (nav wiring), `src/app_web.py` (only `get_roster_data` for logo + 2 new methods `get_rival_promotions` + `get_rival_roster`).
**Scope:**
- CR-7: roster promo logo + weight distribution gender toggle
- CR-8: fighter_profile.js Career tab label "BELTS HE'S WON FOR YOU" → "BELTS WON"
- CR-9: build "The Competition" screen (rival promos list + view rival roster)

### Why split this way
- dashboard.js is touched by CR-5 + CR-6 — both owned by Subagent C.
- roster.js + fighter_profile.js + new screen — all owned by Subagent D.
- app_web.py is touched by both — but they touch DIFFERENT methods (get_dashboard_data vs get_roster_data + 2 new methods), so no conflict.

Both subagents can run in parallel without file-level conflicts.

---

## 7. Out of scope (defer to later phases)

- Phase E2 (real PPV/broadcast model) — NEXT phase after CR-5..9
- Phase E3 (player financial levers) — includes contract negotiation + poaching from rival promos
- Phase E4 (Staff Market screen)
- Building out the other 13 placeholder screens — Phase S
- "Sign from rival promo" flow (poaching) — Phase E3
- Roster comparison view (your roster vs rival's) — possible Phase S feature

---

## 8. After CR-5..9 ship

Per `docs/MASTER_PLAN.md`:
- **Phase E2** (real PPV/broadcast revenue model) is the next planned phase.
- Estimated 3-4 dev-days.
- Replaces the flat `$500k for ppv_global` lookup with `buyrate × price × households`, scales with card quality.
- Source doc: `docs/ECON_STAFF_PLAN.md` §3.

Supervisor sign-off after CR-5..9 will cover:
- **Completeness**: all 5 CRs implemented + tested
- **Wiring**: API methods registered, nav wired, no broken links
- **Voice**: interpretation phrases used (no raw numbers where phrases exist)
- **Design**: visual consistency with existing screens (gold accents, section headers, color-coded chips)
- **Reward**: GPT's 5 rewards reinforced (Discovery via rival promo view, Ownership via promo logo, Agency via gender toggle)
- **Fantasy**: aligns with Soul doc's 5 pillars (Empire Builder — see rival empires; Talent Hunter — scout rival rosters; Puppet Master — watch the competition evolve)
- **Performance**: list view <50ms, roster view reuses existing pattern
