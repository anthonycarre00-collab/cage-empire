> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Re-Planning Reset (August 2026)

> **Status:** PLANNING ONLY. No coding in this phase.
> **Trigger:** User tested 4+ iterations, saw no meaningful improvement.
   Supervisor halted all coding for a full re-planning reset.
> **Root cause:** The world DB is frozen. The simulation has barely
   advanced (1 day from seed). The UI has been rewritten 3+ times but
   the DATA flowing through is identical across iterations — so the
   user sees the same empty/stale screen every time.
> **Audience:** Supervisor (user) — for review + sign-off before any
   further coding begins.

---

## 0. The Brutal Truth

After deep analysis (subagent ingested all planning docs, the 519-page
spec PDF, the Soul doc, the current build code, and the live production
DB), the picture is clear:

**The visual redesign plan was sound. The 24-component library is
well-built. The theme system is solid. The CTk theme override was
removed. The fonts finally resolve in the test environment.** All of
that is real and verified in code.

**BUT** — the user is still seeing a lifeless screen because:

1. **`news_items` table is EMPTY (0 rows).** The Dashboard's "Recent
   News" section ALWAYS shows the EmptyState card. The user's complaint
   "no data was being pulled through" was **literally correct**.

2. **`daily_headlines` has 4 rows, all from world-seed day (2026-07-20).**
   The Top Story card shows the same 4 headlines forever. They never
   regenerate because the sim hasn't advanced.

3. **`events` table has 1,884 events, ALL `status='completed'`.** ZERO
   scheduled events. The "Next Event" card always falls back to "no
   upcoming events."

4. **`interpretation_cache_meta.engine_version` is STILL '1.5.0'** —
   even though the CODE says '1.6.0' (Phase 0 bump). The cache rebuild
   only triggers on Advance Day, and the sim has only advanced 1 day
   from seed. The 8-variant `_EXT` phrase banks exist in code but
   **never reached the DB**. Only 15 distinct momentum phrases exist
   (the original 3-variant × 5 labels).

5. **98.3% of fighters (4,376/4,450) have `momentum='stable'`** sharing
   just 3 phrases: "neither hot nor cold right now" (1,501×), "holding
   steady" (1,459×), "form has been consistent" (1,416×). The Fighter
   Watch cards all show the same string.

6. **`finance_transactions` has only 10 rows, all on the same day.** The
   cash sparkline shows a flat line with 1 data point.

**This is not a UI problem. This is a frozen-world problem.** The user
has been told the dashboard was rewritten 3+ times. They couldn't see a
difference because the DATA flowing through the rewritten components
was identical across iterations.

---

## 1. The Performance Issue You Raised

You said: "the table of fighters on main Roster screen contains full db
of fighters but is then filtered to be promotion specific can this not
be filtered earlier when player chooses promotion or and only update if
a fighter joins/leaves would it be better coz those tables are super
slow to load/render."

**Diagnosis (I measured it):**

| Query | Rows returned | SQL time | Bottleneck |
|---|---|---|---|
| Roster (promo 1) | 60 fighters | 0.9ms | NOT the SQL |
| Free Agents (all unsigned) | 4,138 fighters | 1.2ms | NOT the SQL |
| Free Agents with LIMIT 20 | 20 fighters | 0.0ms | NOT the SQL |

**The SQL is fast** (thanks to the Phase 4 indexes). The bottleneck is
the **WIDGET rendering**: building 20 FighterRow widgets, each with 6
cells, each cell with CTkFrame + CTkLabel/HyperlinkLabel + 4 event
bindings (Enter/Leave/Button-1/Double-Button-1). That's ~120 widget
constructions + ~480 event bindings per page render = ~500ms.

**Your suggestion is correct + I'll expand it:**

1. **Push LIMIT/OFFSET to SQL** — currently the Free Agents query
   fetches all 4,138 rows, stores them in a Python list, sorts in
   Python, then slices to 20 for the current page. Should be:
   `SELECT ... LIMIT 20 OFFSET ?` at the DB level + a separate
   `SELECT COUNT(*)` for pagination. Saves ~480 rows of Python
   processing per refresh.

2. **Cache the query result per promotion** — don't re-query on every
   refresh. Cache the (promo_id, filter, search, sort) → row list.
   Invalidate on: sign fighter, cut fighter, advance day, theme change.
   Your exact suggestion: "only update if a fighter joins/leaves."

3. **Diff-based widget updates** — currently `set_rows()` destroys all
   20 rows + rebuilds them on every refresh. Should: diff old rows vs
   new rows, only update the cells that changed (e.g., if only the
   "Form" column changed, update that one label, don't rebuild the
   whole row). Saves ~90% of widget work on re-renders.

4. **Reduce per-row widget count** — the current FighterRow has 4 event
   bindings per cell × 6 cells = 24 bindings per row. Most of these
   are redundant (the row frame already has the bindings; the cell
   labels don't need their own). Cut to ~6 bindings per row.

5. **Virtualized rendering (P2 future)** — only render the visible
   rows, not all 20. CTkScrollableFrame doesn't support this natively;
   would need a custom Canvas-based virtual list. This is the nuclear
   option for when the roster grows to 10,000+ fighters.

**Estimated impact:** Roster refresh from ~500ms → ~50ms (10x faster).
Free Agents refresh from ~500ms → ~80ms (6x faster).

---

## 2. Why The User Sees No Difference — Ranked

| # | Reason | Probability | Evidence |
|---|---|---|---|
| 1 | **World DB is frozen** (0 news, 0 scheduled events, 15 stale phrases, 1 cash data point) | **VERY HIGH** | Direct DB queries confirm. The sim clock shows current_day=1. |
| 2 | **`__pycache__` stale on user's Windows machine** | HIGH | User's own words: "either my cache didnt clear." Phase 1.5's contrast regression would persist. |
| 3 | **Fonts not loading on Windows** | MEDIUM-HIGH | Test env (Linux + Xvfb) shows ✓ for all 7 fonts, BUT `_install_fonts_to_user_dir()` on Windows copies TTFs to `%LOCALAPPDATA%/Fonts` without calling `AddFontResource` or broadcasting `WM_FONTCHANGE`. Windows may silently fall back to system sans. |
| 4 | **Visual magnitudes too subtle** | MEDIUM | noise_grain at 3% opacity is below threshold of perception. bg_card_elevated luminance delta of 18 is on the edge. The user wants DRAMATIC change, not subtle improvement. |
| 5 | **Components built but fed monotonic data** | LOW | Components ARE used (16 of 24 on Dashboard). But MomentumRing shows the same color for all 3 watch cards because 98% of fighters are 'stable'. FormMeter works (varied W/L). |
| 6 | **CTk framework can't deliver** | LOW | The demo GIF the user linked uses the same techniques we use (PIL compositing, Canvas drawing, after() animations). The issue is execution, not framework. |

---

## 3. The 10 "WOW" Items (from gap analysis, prioritized)

These are the specific changes that would make the user feel genuine
improvement. Ranked by impact-to-effort ratio.

### Tier 1: Do FIRST (unblocks everything else)

**#1. Run the simulation forward 30 in-game days** (Effort: S, 1 hour)
- Script calls `services.clock.advance_day(conn)` 30 times
- Populates: news_items, scheduled events, finance_transactions, fresh
  daily_headlines, fight_history results, fighter_descriptors cache
  rebuild (triggers ENGINE_VERSION mismatch → 8-variant phrases)
- **This single 1-hour script run will produce more visible change than
  the last 3 UI rewrites combined.**
- Soul fantasy served: ALL 5 (anticipation requires the world to be
  alive + changing)
- User complaint addressed: "no data was being pulled through"

**#2. Verify fonts load on Windows** (Effort: S, 30 min)
- Ship a 1-line debug script: `print(sorted(root.tk.call("font",
  "families")))` → save to `font_check.txt`
- Ask the user to run it + send back the file
- If Inter/Oswald/JetBrains Mono/Source Serif Pro are NOT in the list,
  every "font fix" we shipped is invisible
- If they're missing, fix Windows font registration: call
  `AddFontResource` via ctypes + broadcast `WM_FONTCHANGE`
- User complaint addressed: "better fonts would do us a world of good
  but seems to keep failing"

**#3. Give the user a permanent cache-clear solution** (Effort: S, 15 min)
- Modify `PLAY.bat` to auto-delete `__pycache__` folders on every launch
- Add a `--clear-cache` CLI flag as alternative
- User complaint addressed: "give me a non techy simple way to clear it"

### Tier 2: Do AFTER Tier 1 (dramatic visual improvement)

**#4. Increase visual magnitudes** (Effort: S, 1 hour)
- noise_grain: 3% → 8% opacity
- chain_link on header: 8% → 15% opacity
- cage_watermark: 5% → 12% opacity
- bg_card_elevated: luminance delta 18 → 30+ (change from #262a30 to
  #2f343d or #343a45)
- User complaint addressed: "styling rarely changes much in each
  iteration" + "need textures or backgrounds"

**#5. Full-bleed cage-fence background texture on Dashboard** (Effort: S, 1 hour)
- Tile chain_link_dim.png across the Dashboard's bg_base at 15% opacity
- Add vignette darkening the edges (use existing
  vignette_fight_night.png)
- Make the player feel like they're looking at a promoter's desk in an
  arena
- Soul fantasy served: Empire Builder (the control room metaphor)
- User complaint addressed: "need textures or backgrounds" + "MMA
  elements/visuals"

**#6. Hero "Top Story" card with real fighter portrait** (Effort: M, 3-4 hours)
- Replace the text-only Top Story with: full-bleed gradient background,
  96×96 portrait (procedurally generated initials-based — the visual
  plan §8.2 P1 promised this script), fighter name in Oswald display
  font, LONG-variant headline, 2-sentence body in Inter italic, topic
  chips with icons
- Soul fantasy served: Talent Hunter + Kingmaker
- User complaint addressed: "MMA elements/visuals" + "friendlier feel"

**#7. Real scheduled event with countdown timer** (Effort: M, 2-3 hours)
- After running the sim forward (item #1), the Next Event section shows
  a real upcoming event: event name, date, main event matchup, title
  fight indicator, live countdown ("3 days, 14 hours until fight
  night")
- Soul fantasy served: ALL 5 (anticipation is the real dopamine)
- User complaint addressed: "no data was being pulled through"

### Tier 3: Do AFTER Tier 2 (polish + new experiences)

**#8. Generate the 32 P0 icons** (Effort: M, 2-3 days)
- 14 nav icons + 8 status icons + 10 topic icons
- Lucide/Phosphor outlined style, 2px stroke, single-color (gold)
- Wire into sidebar (nav), FighterRow (status), NewsCard (topic)
- User complaint addressed: "still something missing to give it a
  friendlier feel" + "database tool" vibe

**#9. Pre-Fight Build-Up screen (Phase 7a)** (Effort: L, 5-7 days)
- Build JUST the Pre-Fight Build-Up phase of the Fight Resolution
  screen: Tale of Tape (two fighter portraits side-by-side), pundit
  predictions (3 named pundits), memory setup (prior meetings),
  storyline context (rivalry heat meter)
- NO live fight yet — just the buildup. End with a "▶ Start Fight"
  placeholder button.
- Soul fantasy served: ALL 5 (the marquee dopamine moment)
- User complaint addressed: "the four screens remain exactly the same"
  — this is a FIFTH screen, not a rewrite

**#10. "Fighter of the Week" spotlight** (Effort: M, 3-4 hours)
- New Dashboard section that rotates weekly to a different fighter
- Hero portrait + name in Oswald + 3-sentence LONG-variant narrative
  (champion reads differently from prospect reads differently from
  veteran)
- Soul fantasy served: Historian + Talent Hunter + Kingmaker
- User complaint addressed: "the four screens remain exactly the same"
  — this ROTATES, so it visibly changes weekly

---

## 4. The Performance Fix Plan (from §1, detailed)

**Current state:** Roster refresh ~500ms, Free Agents refresh ~500ms.
The SQL is fast (0.9ms / 1.2ms). The bottleneck is widget rendering.

**Phase A: SQL pagination (Effort: S, 2 hours)**
- Push `LIMIT 20 OFFSET ?` to the Free Agents query
- Add a `SELECT COUNT(*)` for pagination total
- Don't fetch 4,138 rows then slice in Python
- Impact: Free Agents query goes from 1.2ms + Python sort of 4,138 rows
  → 0.0ms + Python sort of 20 rows

**Phase B: Query result cache (Effort: M, 4 hours)**
- Cache the (promo_id, filter, search, sort) → row list in a module-level
  dict with a TTL or invalidation flag
- Invalidate on: sign fighter, cut fighter, advance day, theme change
- Your exact suggestion: "only update if a fighter joins/leaves"
- Impact: Re-renders (navigation back to Roster, pagination) skip the
  SQL entirely

**Phase C: Diff-based widget updates (Effort: L, 6-8 hours)**
- Currently `set_rows()` destroys all 20 rows + rebuilds
- New: `update_rows(new_rows)` diffs old vs new, only updates changed
  cells
- If only the "Form" column changed, update that one label per row,
  don't rebuild the row
- Impact: Re-renders go from ~500ms → ~50ms (10x faster)

**Phase D: Reduce per-row bindings (Effort: S, 2 hours)**
- Current: 4 bindings per cell × 6 cells = 24 bindings per row
- New: 1 binding on the row frame only (clicks propagate to children
  via `add="+"`), 0 bindings on individual cells/labels
- Impact: Widget construction ~40% faster

**Total estimated impact:** Roster refresh 500ms → 50ms. Free Agents
refresh 500ms → 80ms.

---

## 5. Revised Execution Order

Based on the gap analysis, the ORIGINAL phase order (Phase 3 shell →
Phase 5 Roster → Phase 6 Profile) is WRONG. The user can't see UI
improvements on a frozen world. The revised order:

### Step 1: UNFREEZE THE WORLD (do this FIRST, before any UI work)
- Run the simulation forward 30 days (item #1)
- Verify the cache rebuilds with 8-variant phrases
- Verify news_items, scheduled events, finance_transactions populate
- **Effort: 1 hour. Impact: more visible change than the last 3 UI
  rewrites combined.**

### Step 2: VERIFY THE USER'S MACHINE (do this SECOND)
- Ship the font-check debug script (item #2)
- Give the permanent cache-clear solution (item #3)
- Ask the user to run the font check + clear cache + relaunch
- **Effort: 45 min. Impact: confirms whether the last 3 iterations were
  invisible due to cache/fonts or due to frozen data.**

### Step 3: DRAMATIC VISUAL MAGNITUDE (do this THIRD)
- Increase texture opacities (item #4)
- Full-bleed cage-fence background (item #5)
- Hero Top Story card with portrait (item #6)
- **Effort: 5-6 hours. Impact: the user WILL see a difference — these
  are dramatic, not subtle.**

### Step 4: PERFORMANCE FIXES (do this FOURTH)
- SQL pagination (Phase A)
- Query result cache (Phase B)
- Diff-based widget updates (Phase C)
- Reduce per-row bindings (Phase D)
- **Effort: 14-16 hours. Impact: tables load 6-10x faster.**

### Step 5: THEN resume the original phase plan
- Phase 3: App Shell Rewrite (sidebar collapse, top bar, no bottom bar)
- Phase 5: Roster + Free Agents redesign (using the component library +
  the performance fixes from Step 4)
- Phase 6: Fighter Profile redesign
- Phase 7a: Pre-Fight Build-Up screen (the marquee moment)
- **Only after Steps 1-4 are done + the user has confirmed visible
  improvement.**

---

## 6. Framework Decision: STAY with CustomTkinter

The gap analysis recommends staying with CTk. Reasoning:

1. **The user's complaints are framework-agnostic.** Frozen data, stale
   cache, fonts not loading, subtle visuals — these would happen in
   PyQt6, pywebview, or DearPyGui too.

2. **CTk CAN deliver the visual richness.** The demo GIF the user linked
   uses the same techniques we already use: PIL compositing for
   gradients, Canvas drawing for custom visualizations, `after()`
   callbacks for animations, custom widget subclasses. We have 24
   custom widgets. We're not missing any techniques.

3. **Migration cost is prohibitive.** A pivot to PyQt6 or pywebview
   would be 6-12 weeks of rewrite. The user is already frustrated with
   the pace. A pivot would extend the timeline by 3+ months with no
   guarantee of better results.

4. **The supervisor already locked the framework** (GUI_PLAN §3:
   "Status: Locked. No changes.")

**If after Steps 1-4 the user STILL says "no difference," THEN consider
a pivot.** But the evidence strongly suggests the issue is execution
(frozen data, stale cache, subtle magnitudes, Windows font loading),
not the framework.

---

## 7. What Went Wrong (honest post-mortem)

1. **I over-indexed on UI code + under-indexed on data.** The user's
   complaint "no data was being pulled through" was literally correct,
   and I didn't verify the DB state until forced to by this re-planning
   reset. I should have checked `news_items` count + `daily_headlines`
   count + `interpretation_cache_meta.engine_version` BEFORE shipping
   any UI rewrite.

2. **I shipped Phase 0 (ENGINE_VERSION bump) but didn't verify it took
   effect.** The code change was correct, but the cache rebuild only
   triggers on Advance Day. I should have run `advance_day()` once in a
   script to trigger the rebuild + verify the phrases changed, BEFORE
   telling the user it was shipped.

3. **I made visual changes too subtle.** noise_grain at 3% opacity is
   below perception. bg_card_elevated luminance delta of 18 is on the
   edge. The user wants DRAMATIC change, not subtle improvement. I
   should have erred on the side of "too much" and dialed back, not
   "too little" and hoped the user would notice.

4. **I didn't verify fonts on the user's actual machine.** The test env
   (Linux + Xvfb) showed ✓ for all 7 fonts, but Windows font
   registration is different (requires `AddFontResource` + `WM_FONTCHANGE`
   broadcast). I should have shipped a font-check debug script in Phase
   1, not Phase 6.

5. **I didn't give the user a permanent cache-clear solution.** The
   `__pycache__` issue has been identified multiple times in worklog
   entries, but I never modified `PLAY.bat` to auto-clear it. The user
   shouldn't have to manually search for `__pycache__` folders.

---

## 8. Open Questions for the Supervisor

1. **Approve running the simulation forward 30 days?** This will change
   the world DB (irreversibly — but we can backup first). The sim will
   generate news, events, fight results, fresh headlines. The world
   will become "alive." **[RECOMMENDED: yes, backup first]**

2. **Approve the revised execution order?** Steps 1-4 before resuming
   the original phase plan. **[RECOMMENDED: yes]**

3. **Approve the performance fix plan (§4)?** SQL pagination + query
   cache + diff-based widget updates + reduced bindings. **[RECOMMENDED:
   yes — the user specifically asked for this]**

4. **Approve increasing visual magnitudes (item #4)?** This will make
   textures more visible (some may say "too visible"). We can dial back
   if needed. **[RECOMMENDED: yes — subtle has failed]**

5. **Should I ship the font-check debug script + ask the user to run
   it?** This is the only way to verify fonts load on the user's actual
   Windows machine. **[RECOMMENDED: yes]**

6. **Should I modify PLAY.bat to auto-clear __pycache__?** This solves
   the cache issue permanently. **[RECOMMENDED: yes]**

---

## 9. Next Steps (awaiting supervisor sign-off on §8)

1. **Supervisor reviews this doc + marks decisions on §8.**
2. **If approved:** Step 1 (unfreeze the world) runs immediately.
3. **Then:** Step 2 (font check + cache clear) ships.
4. **Then:** Step 3 (dramatic visual magnitude) ships.
5. **Then:** Step 4 (performance fixes) ships.
6. **Then:** User tests. If "wow," resume original phase plan. If "no
   difference," diagnose further (possibly framework pivot).

**Do NOT start any new screen (Phase 3 shell, Phase 5 Roster rewrite,
Phase 6 Profile rewrite, Phase 7 Fight Night) until Steps 1-4 are done
+ the user has confirmed visible improvement.**

---

*End of Re-Planning Reset document. Awaits supervisor sign-off on §8
before any coding begins.*


---

## 10. DB Pruning / Archival Strategy (NEW — per user request)

> User: "ensure that data/news/memories and whatever else our db is
> capturing is pruned 'culled' or archived periodically to avoid
> engorging the db."

### 10.1 The Problem

After running the sim forward 30 days with all services active, the DB
grew significantly:
- news_items: 0 → 524 (will grow ~15-20/day = ~6,000/year)
- daily_headlines: 4 → 112 (will grow ~4/day = ~1,460/year)
- fight_history: 3,598 → 3,614 (will grow ~5/event × ~10 events/week = ~2,600/year)
- finance_transactions: 10 → 41 (will grow ~2/day = ~730/year)
- social_posts: 132 (will grow ~5/day = ~1,825/year)
- fighter_memory_links: 96 (will grow ~2/fight = ~5,200/year)
- training_camps: 50 → 126+ (completed camps should be archived)
- injuries: 390 (resolved injuries should be archived)

Over a 10-year in-game career, this could add 60,000+ news items, 26,000+
fight history rows, 18,000+ social posts — the DB would grow to 100+ MB
and queries would slow.

### 10.2 Pruning Rules (per table)

| Table | Retention | Action | Trigger |
|---|---|---|---|
| `news_items` | Last 365 days (1 in-game year) | Older rows: DELETE (or archive to `news_items_archive` table if we want history) | Monthly on Advance Day |
| `daily_headlines` | Last 90 days | Older rows: DELETE (headlines are ephemeral — they're "today's story") | Monthly on Advance Day |
| `social_posts` | Last 180 days | Older rows: DELETE | Monthly on Advance Day |
| `fight_history` | KEEP ALL (career stats depend on it) | No pruning — but add index on fighter_id for query speed (already done in Phase 4) | n/a |
| `finance_transactions` | Last 365 days | Older rows: archive to `finance_transactions_archive` (player may want long-term financial history) | Monthly on Advance Day |
| `fighter_memory_links` | Last 200 per fighter | If a fighter has >200 memory links, delete oldest | Monthly on Advance Day |
| `injuries` (resolved) | Last 365 days | Resolved injuries older than 1 year: DELETE (keep active injuries) | Monthly on Advance Day |
| `suspensions` (expired) | Last 365 days | Expired suspensions older than 1 year: DELETE | Monthly on Advance Day |
| `training_camps` (completed) | Last 90 days | Completed camps older than 90 days: DELETE | Monthly on Advance Day |
| `scouting_reports` | Last 180 days | Reports older than 180 days: DELETE (scouting data goes stale) | Monthly on Advance Day |
| `fight_beats` | Last 365 days | Fight beats for fights older than 1 year: DELETE (the fight_history row stays, just the play-by-play is pruned) | Monthly on Advance Day |
| `commentary_segments` | Last 365 days | Same as fight_beats — prune play-by-play, keep results | Monthly on Advance Day |

### 10.3 Implementation Approach

- **New service:** `src/services/pruning_svc.py` — registers as a
  TICK_ADVANCED subscriber. Runs on the 1st of each in-game month.
- **Idempotent:** safe to run multiple times (uses DELETE WHERE
  date < cutoff).
- **Performance:** batch DELETEs with LIMIT 1000 to avoid locking
  the DB for too long. Runs in a transaction.
- **Archival (P2 future):** for tables where we want long-term history
  (finance_transactions, fight_history), create `_archive` tables that
  store pruned rows. The player can query these from the Finance screen
  ("show 5-year cash history") without bloating the live tables.
- **Configurable:** `player_settings` table gets a `db_pruning_enabled`
  column (default 1). The player can disable pruning if they want to
  keep everything (at the cost of performance).

### 10.4 Estimated Impact

- After 10 in-game years with pruning: DB stays under 50 MB (vs 100+ MB
  without).
- Pruning run: <500ms per monthly tick (batch DELETEs with indexes).
- No player-visible data loss: news older than 1 year is not shown
  anywhere in the UI (the News Feed shows last 20, the Dashboard shows
  last 5).
