> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Fix Plan: Cache Clear + Cash Balance + Event Builder UX + Live Preview

> **Status:** ACTIVE — fix plan for 4 issues reported after Phase E3.
> **Supervisor:** main agent.

---

## 0. Issues

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| F1 | Cache didn't clear — career starts at Alpha (promo 1) | `player_promotion_id=1` stuck in `player_settings` table from prior testing | Clear `player_settings` on app startup if a "fresh game" flag is set, OR add a "Reset Game" button. Simplest: clear `player_promotion_id` + `player_name` in the DB shipped to the user. |
| F2 | $700M+ starting cash is ridiculous | Phase E1 backfilled 2156 finance_transactions for promo 1's 431 historical events, inflating cash from $80M to $793M. All promos have inflated cash from sim-forward testing. | Reset ALL promos' `current_cash` to their `starting_budget`. Delete all backfilled finance_transactions (keep only the seed sponsorship row). This gives a clean economic starting point. |
| F3 | Build Card screen is boring — needs images + easier flow | Event Builder has no visual richness (no venue images, no fighter portraits on the card, plain slider UI) | Add venue images (or styled placeholder cards with capacity icons), add fighter portraits to the card builder, improve the visual hierarchy with better section design, add a "quick pick" flow (recommended venue + default levers). |
| F4 | Live preview section not working | Backend works (verified: `get_event_preview` returns correct data). JS wiring issue — likely the `fetchPreview` DOM replacement fails silently, OR the initial render doesn't fire `fetchPreview` because no venue is selected. | Debug the JS: add console.log to trace the preview flow, fix the DOM replacement, ensure preview fires on venue selection + lever change. |

---

## 1. F1 — Clear stale player_settings

**File:** `data/cage_empire.db` (direct DB update)

```sql
DELETE FROM player_settings WHERE setting_key IN ('player_promotion_id', 'player_name');
```

This ensures the pre-game screen appears on next launch. The user picks their promo fresh.

**Also:** add a "Reset Game" option to the sidebar (bottom, below all nav items) that calls a new API method `reset_game()` which clears `player_settings` + reloads the page. This lets the user restart without editing the DB.

---

## 2. F2 — Reset all promo cash to starting_budget

**File:** `data/cage_empire.db` (direct DB update)

```sql
-- Reset all promos to their starting_budget (clean economic state)
UPDATE promotions SET current_cash = starting_budget;

-- Delete all backfilled finance_transactions (keep only seed sponsorship rows)
-- Seed rows have transaction_date = '2026-01-01' and transaction_type = 'sponsorship'
DELETE FROM finance_transactions
WHERE NOT (transaction_date = '2026-01-01' AND transaction_type = 'sponsorship');
```

This gives every promo a clean starting cash:
- Promo 1 (Alpha): $80M
- Promo 2 (Rival Fight League): $25M
- Promo 3 (Pacific Rim): $20M
- ... etc.

The player starts with a realistic bankroll, not $793M.

---

## 3. F3 — Event Builder UX improvements

**Files:**
- `src/web/js/event_builder.js` — add venue images, fighter portraits, quick-pick flow, better visual hierarchy
- `src/web/css/event_builder.css` — improve styling, add image cards, better slider design
- `src/app_web.py` — `get_event_builder_data` should return venue image paths + fighter portraits

**Improvements:**
1. **Venue cards with images** — each venue card shows a stylized venue image (or a capacity-based icon: 🏟 for arena, 🎭 for theater, etc.) + name + city + capacity + venue_type + rental cost. Selected venue has gold border + checkmark.
2. **Quick Pick flow** — a "Quick Pick" button at the top that auto-selects the recommended venue (best capacity/cost ratio for the player's promo) + default levers. Gets the player to a schedulable state in 1 click.
3. **Fighter portraits on card** — when building the card, show the player's top fighters (by ranking/momentum) as portrait cards. Clicking a fighter adds them to the card. (This is a stretch goal — may defer if too complex.)
4. **Better slider design** — sliders with gradient tracks (red→yellow→green), larger thumb, value bubble above the thumb.
5. **Visual hierarchy** — section headers with icons (🎫 BUILD A CARD, 🏟 PICK YOUR VENUE, 🎚 SET YOUR LEVERS, 📊 PROJECTED OUTCOME). Preview section gets a prominent net-profit display with color-coded background (green/red gradient).

---

## 4. F4 — Live preview fix

**File:** `src/web/js/event_builder.js`

Debug steps:
1. Add `console.log('[eventBuilder] fetchPreview called', state)` at the top of `fetchPreview()`
2. Add `console.log('[eventBuilder] preview result', result)` after the bridge call resolves
3. Add `console.log('[eventBuilder] preview host', prevHost)` before the replaceWith
4. Check if the issue is that `renderPreview()` returns a string but `fetchPreview` tries to use it as DOM

**Likely fix:** The `fetchPreview` function does:
```js
var wrap = document.createElement('div');
wrap.innerHTML = renderPreview();
if (wrap.firstChild) prevHost.replaceWith(wrap.firstChild);
```

But `renderPreview()` returns `<div class="ce-eb-preview">...</div>` — so `wrap.firstChild` IS the new `.ce-eb-preview`. The `replaceWith` should work. BUT: if `prevHost` is null (the `.ce-eb-preview` element doesn't exist in the DOM), the replacement silently fails.

**Root cause hypothesis:** The initial `render()` call outputs `renderPreview()` which returns the "empty" state (`<div class="ce-eb-preview__empty">Pick a venue...</div>`). This is NOT wrapped in `<div class="ce-eb-preview">`. So when `fetchPreview` looks for `.ce-eb-preview`, it doesn't find it → `prevHost` is null → replacement fails silently.

**Fix:** Wrap the empty/loading states in `<div class="ce-eb-preview">` too:
```js
function renderPreview() {
    if (!state.selectedVenueId) {
      return '<div class="ce-eb-preview"><div class="ce-eb-preview__empty">Pick a venue to see your projected outcome.</div></div>';
    }
    var p = state.lastPreview;
    if (!p || !p.ok) {
      return '<div class="ce-eb-preview"><div class="ce-eb-preview__loading">Calculating…</div></div>';
    }
    // ... rest
}
```

Also ensure `fetchPreview` checks for null host:
```js
var prevHost = document.querySelector('.ce-eb-preview');
if (!prevHost) {
    // Fallback: re-render the whole screen
    render();
    return;
}
```

---

## 5. Implementation order

1. F1 + F2: direct DB fix (clear player_settings + reset cash). 1 commit.
2. F4: live preview JS fix. 1 commit.
3. F3: Event Builder UX improvements (venue images, quick pick, better sliders). 1 commit.
4. Run all tests, verify, push.

---

## 6. Acceptance criteria

- [ ] Pre-game screen appears on launch (no stuck promo)
- [ ] All promos have current_cash = starting_budget (promo 1 = $80M, not $793M)
- [ ] Live preview updates when venue selected + levers changed
- [ ] Event Builder has visual richness (venue images/icons, better sliders, section icons)
- [ ] Quick Pick button auto-selects recommended venue + defaults
- [ ] All tests pass (save/load, news, finance E1/E2/E3)
- [ ] No regressions

---

## 7. After fixes

Continue with Phase E4 (Staff Market screen) per MASTER_PLAN.
