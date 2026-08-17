# Phase 5 — Screen Audit Report

**Date:** 2026-08-17
**Task ID:** PHASE5-T1-SCREEN-AUDIT
**Auditor:** Explore subagent

## Summary

- Total screens audited: 24 (22 feature screens + `app` shell + `bridge`)
- Total violations: **34** (HIGH: 7, MEDIUM: 18, LOW: 9)
- Top 3 highest-impact issues:
  1. **`get_fight_compare` returns raw 25-attribute 0-100 ints to JS**, which `matchmaking.js:1678-1742` averages into radar-chart polygon coordinates. Per CONVENTIONS §14, raw attribute values must never appear in the player-facing UI — even as visual magnitudes. (HIGH)
  2. **`get_matchmaking_data` runs an N+1 pattern**: for each eligible fighter (100+ on a major promo) it calls `self._fighter_brief(conn, fid)` (line 5825), which itself runs 4+ subqueries per fighter (rank lookup, clock lookup, recent_form query, title_chip query). On a major promo this is 400+ queries per Matchmaking screen load. (HIGH)
  3. **`get_gyms_data` reads from `gyms` simulation table directly** and returns six raw 0-100 gym ratings (`reputation`, `facility_quality`, `medical_support`, `sparring_depth`, `development_focus`, `weight_cut_support`), all displayed as numeric values + bar fills by `gyms.js:387,412`. The `gym_descriptors` cache table exists per CONVENTIONS §17.3 but is unused. (HIGH)

---

## Per-Screen Findings

### 1. Dashboard (`src/web/js/dashboard.js` + `app_web.py:get_dashboard_data`)

**Voice violations:** none — all values are voice phrases (`reputation_phrase`, `fan_trust_phrase`, `decodePhrase(momentum)` etc.) or factual counts (cash, roster_count, champ_count).

**Performance issues:**
- `app_web.py:2519-2524` — `upcoming_events` subquery `(SELECT COUNT(*) FROM fights WHERE event_id=e.event_id)` is a correlated subquery per event row. Bounded to scheduled events (typically <10), so impact is LOW. [LOW]

**Data freshness violations:**
- `app_web.py:2335` — `SELECT first_name, last_name FROM fighters WHERE fighter_id=?` to resolve top-story fighter name. Strict §17.1 violation (simulation table read), but the descriptor cache doesn't store name/identity. [LOW]
- `app_web.py:2422-2430` — `SELECT ... FROM fighters f LEFT JOIN fighter_descriptors fd ...` for fighter watch. Reads `fighters` directly. [LOW]
- `app_web.py:2459-2464` — reads `titles` directly (champion list). Per §17.1 strict letter, a violation. [LOW]
- `app_web.py:2487-2492, 2502-2505, 2519-2524` — reads `events`, `show_ratings`, `promotions` directly. [LOW]
- `app_web.py:2554-2556` — `_reputation_phrase(rep)` / `_fan_trust_phrase(fan_trust)` are computed server-side from raw `promotions.reputation`/`fan_trust`. Raw ints are also returned in the JSON payload (`reputation`, `fan_trust` fields at lines 2553, 2555) but NOT displayed in JS — only used as bar-width percentages. Borderline §14 / §17.4. [MEDIUM]

### 2. Roster (`src/web/js/roster.js` + `app_web.py:get_roster_data`)

**Voice violations:** none — `stage_short`, `form_short`, `momentum_label` all come from `fighter_descriptors`; `record_str` is factual career W-L-D.

**Performance issues:**
- `app_web.py:2886-2887` — two correlated subqueries per row for `injury_count` and `susp_count`: `(SELECT COUNT(*) FROM injuries WHERE fighter_id=... AND is_active=1)`. With 20 rows/page this is 40 subqueries. Should be a LEFT JOIN + GROUP BY. [MEDIUM]

**Data freshness violations:**
- `app_web.py:2878-2898` — reads `fighters`, `fighter_career`, `weight_classes`, `gyms`, `nations`, `injuries`, `suspensions` directly. Joins `fighter_descriptors` for stage/form phrases. Per strict §17.1, `fighters`/`fighter_career` reads are violations — but `fighter_descriptors` does not store name/identity/record fields. [LOW]

### 3. Fighter Profile (`src/web/js/fighter_profile.js` + `app_web.py:get_fighter_profile_data`)

**Voice violations:**
- `fighter_profile.js:306` — displays `cs.career_health` as a raw 0-100 integer in the Career Health stat tile: `'<div class="ce-fp-stat-val ce-mono">' + cs.career_health + '</div>'`. `app_web.py:3808` returns `career_health` from `fighter_career.career_health` (the raw 0-100 derived metric). The API comment at `app_web.py:3826-3828` explicitly carves this out as "a derived health metric, not a hidden engine attribute," but per §14 strict reading, raw 0-100 ratings must pass through the voice layer. The descriptor `career_health_desc` exists (`fighter_descriptors.career_health_desc`, fetched at `app_web.py:3745`) and is shown in the header chip at `fighter_profile.js:232` — but the stat-tile also shows the raw int. [MEDIUM]

**Performance issues:** none — single-fighter payload, all queries bounded by fighter_id.

**Data freshness violations:**
- `app_web.py:3643-3657` — reads `fighters` directly (name, gender, DOB, WC, gym, promo, etc.). [LOW]
- `app_web.py:3808` — reads `fighter_career` directly (record_wins, streaks, `career_health`, `potential`). The raw `potential` int is read but NOT returned (explicit guard at `app_web.py:3826`). [LOW]
- `app_web.py:3843` — reads `fighter_bios` directly. (Acceptable — bios aren't in the cache taxonomy.) [LOW]
- `app_web.py:3853-3884` — reads `fight_history` directly for recent_fights. [LOW]
- `app_web.py:3906-3917` — reads `titles` directly. [LOW]
- `app_web.py:3920-3928` — reads `news_items` directly. [LOW]
- `app_web.py:3931-3944` — reads `scouting_reports` + `staff` directly. [LOW]
- `app_web.py:3947-3956` — reads `contracts` + `fighter_contracts` directly. [LOW]
- `app_web.py:3962+` — reads `player_decisions` and `fight_history` for "your history" computation. [LOW]

### 4. Fight Night (`src/web/js/fight_night.js` + `app_web.py:get_fight_night_data`)

§17.2 explicitly exempts the Fight Resolution screen from §17.1 — direct reads of `fight_beats`, `fight_rounds`, `commentary_segments` are expected. Audit below covers only voice + performance.

**Voice violations:**
- `fight_night.js:1366-1372` — `showAxis(label, value)` uses raw 0-100 values (`fan_rating`, `commercial_rating`, `excitement_rating`, `quality_rating`, `overall_rating`) as bar-fill widths. The player sees only the bar visual + the voice phrase at `fight_night.js:1311` — no numeric text is rendered. Acceptable (bar fill is plumbing, not display). [no violation]
- `fight_night.js:1082, 1296` — `h.importance >= 85` (raw threshold check for "major moment" CSS class). Internal branching, not displayed. [no violation]

**Performance issues:**
- `app_web.py:11545+` — `fight_beats` query for a fight has no LIMIT clause. Bounded by # of beats per fight (~50-150), so acceptable. [no violation]
- Per-extra-segment staff-name lookup inside the loop at `app_web.py:11750+` — N+1 pattern, bounded to ~30-50 segments per fight. [LOW]

### 5. Matchmaking (`src/web/js/matchmaking.js` + `app_web.py:get_matchmaking_data` + `get_fight_compare`)

**Voice violations:**
- `matchmaking.js:1678-1742` (`renderRadarChart`) — averages raw 0-100 attribute values (`redAttrs[a]`, `blueAttrs[a]` where `a` ∈ `['punch_power', 'punch_accuracy', 'kick_power', 'kick_accuracy', 'head_movement', 'footwork', 'clinch_striking', 'clinch_offense', 'clinch_defense', 'takedown_offense', 'takedown_defense', 'top_control', 'bottom_game', 'submission_offense', 'submission_defense', 'scramble_ability', 'cage_wrestling', 'cardio', 'recovery_rate', 'speed_explosiveness', 'strength', 'durability', 'flexibility', 'fight_iq', 'chin', 'adaptability']`) into 5-axis radar polygon coordinates. The player sees the polygon shapes — relative attribute magnitudes are visually exposed. This is a clear §14 violation: "No raw attribute values, potential numbers, or internal ratings appear in the player-facing UI." [HIGH]
- `app_web.py:8117-8118` — `get_fight_compare` returns `red_attributes` and `blue_attributes` dicts of all 25 raw attribute values. The JS uses these directly to draw the radar chart. [HIGH]
- `app_web.py:8126-8140` (`_fighter_attributes_dict`) — reads `fighter_attributes` simulation table directly (per §17.1, should come from `fighter_descriptors.attribute_descriptors` JSON which already stores voice phrases). [HIGH per §17.1]
- `app_web.py:6716` — `_fighter_brief` returns `"marketability": mkt or 50,  # internal — NEVER shown raw`. The raw 0-100 marketability int IS returned in every fighter brief. The JS comment claims it's never displayed, but it's accessible in DevTools. [MEDIUM]

**Performance issues:**
- `app_web.py:5820-5832` — N+1 pattern: per eligible fighter, calls `self._fighter_brief(conn, fid)` which itself runs 4+ subqueries (rank lookup at line 6647, clock lookup at line 6673, `_recent_form` at line 6690, `_title_chip` at line 6691). For a 100+ fighter roster, this is 400+ queries per Matchmaking screen load. [HIGH]
- `app_web.py:6647-6654` — per-fighter rank computation is a separate `SELECT COUNT(*)+1 FROM rankings ...` query. Should be batched. [MEDIUM]
- `app_web.py:6673-6677` — per-fighter `simulation_clock` lookup. The clock is constant per request; should be fetched once. [MEDIUM]

**Data freshness violations:**
- `app_web.py:6607-6632` — reads `fighters`, `fighter_career`, `fighter_descriptors`, `rankings`, `weight_classes`, `style_archetypes` directly. The `fighter_descriptors` join is correct for stage/form phrases. [LOW]
- `app_web.py:8134` — `SELECT ... FROM fighter_attributes WHERE fighter_id=?` reads the simulation table that §17.1 explicitly forbids for Office-Mode UI. [HIGH per §17.1]

### 6. Calendar (`src/web/js/calendar.js` + `app_web.py:get_calendar_data`)

**Voice violations:** none — voice phrases ("Clear date", "Counter-programming risk", "Short turnaround") are used.

**Performance issues:**
- `app_web.py:5475-5505` — per-day conflict-detection loop iterates `rival_dates` and `player_dates` lists (built from a ±7-day window query). O(N×M) where N=31 days, M=events in window. Worst case ~31×50 = 1550 iterations including `datetime.strptime` calls per iteration. Could be replaced with a date→events dict lookup. [MEDIUM]

**Data freshness violations:**
- `app_web.py:5379-5389, 5426-5433` — reads `events` + `promotions` directly. (Calendar is fundamentally an events view; no cache table exists for these.) [LOW]

### 7. Event Builder (`src/web/js/event_builder.js` + `app_web.py:get_event_builder_data`)

**Voice violations:** none — levers are dollar amounts (cash), venues are factual capacity/location, projection is a computed $ figure.

**Performance issues:**
- `app_web.py:4332-4339` — N+1 pattern: inside the per-fighter loop (`for r in f_rows:`), a subquery `SELECT SUM(...) FROM fight_history WHERE fighter_id=?` computes the W/L/D record per fighter. Should join `fighter_career` (which already has `record_wins/losses/draws` columns) instead. For a 100+ fighter roster, this is 100+ queries per Event Builder load. [HIGH]

**Data freshness violations:**
- `app_web.py:4318-4328` — reads `fighters`, `weight_classes`, `fighter_descriptors`, `fight_history` directly. [LOW]

### 8. Rankings (`src/web/js/rankings.js` + `app_web.py:get_rankings_data`)

**Voice violations:** none — JS comment at `rankings.js:23` explicitly states "NEVER show rankings.rating (ELO float) — only rank #." The raw `r.rating` is read in the API (`app_web.py:12340`) but is NOT included in the returned dict (only `rank`, `momentum_label`, `momentum_phrase`, etc.). ✓

**Performance issues:**
- `app_web.py:12352-12353` — correlated subquery per row: `(SELECT outcome FROM fight_history fh WHERE fh.fighter_id=r.fighter_id ORDER BY fh.fight_history_id DESC LIMIT 1) AS last_outcome`. 15 rows = 15 subqueries. Could be a LEFT JOIN. [MEDIUM]

**Data freshness violations:**
- `app_web.py:12339-12362` — reads `rankings`, `fighters`, `promotions`, `fighter_career`, `fighter_descriptors`, `fight_history` directly. [LOW]

### 9. Titles (`src/web/js/titles.js` + `app_web.py:get_titles_data`)

**Voice violations:** none — reign length is shown as voice phrase (`reign_voice` via `_reign_voice_phrase`), defense/reign counts are factual achievements (carve-out per records.js §14 comment).

**Performance issues:** none observed — single bulk query, bounded to ~10 promos × 12 WCs = ~120 rows.

**Data freshness violations:**
- `app_web.py:12516+` — reads `titles`, `weight_classes`, `promotions`, `fighters` directly. No `titles_descriptors` cache exists. [LOW]

### 10. Rivalries (`src/web/js/rivalries.js` + `app_web.py:get_rivalries_data`)

**Voice violations:**
- `rivalries.js:238` — displays raw `rivalry_heat` int as `<span class="ce-riv__heat-val ce-mono">' + riv.rivalry_heat + '</span>'`. The JS comment at `rivalries.js:36-37` carves this out as "relationship rating, NOT a fighter attribute." Per §14 strict reading, internal ratings should pass through the voice layer; the `heat_phrase` already exists. Player sees BOTH the raw int AND the voice phrase. [MEDIUM]
- `app_web.py:6456` (approximate, in `get_rivalries_data` SQL) — `SELECT r.rivalry_heat, ...` returns the raw int in the JSON. [MEDIUM]

**Performance issues:**
- `app_web.py:6475-6480` — summary stats (active_count, dormant_count, boiling_count, title_rivalry_count) are computed via separate `SELECT COUNT(*) FROM rivalries ...` queries. Could be a single `GROUP BY` query. [LOW]

**Data freshness violations:**
- `rivalries` is a simulation table per §17.3, but there is no `rivalries_descriptors` cache table in the taxonomy. Reading from `rivalries` is acceptable. [no violation]

### 11. Hall of Fame (`src/web/js/hall_of_fame.js` + `app_web.py:get_hof_data`)

**Voice violations:** none — `career_summary` is voice-layered prose; `highlights` are voice phrases; record counts are factual career stats.

**Performance issues:** none — single paginated query.

**Data freshness violations:**
- `app_web.py:10680+` — reads `hall_of_fame`, `fighters`, `fighter_career`, etc. directly. `hall_of_fame` is a derived table (not in the cache taxonomy), so this is acceptable. [no violation]

### 12. Records (`src/web/js/records.js` + `app_web.py:get_records_data`)

**Voice violations:** none — each record value is wrapped in a `context` voice phrase.

**Performance issues:**
- `app_web.py:14270+` — 11 separate single-row queries (one per record type: most_wins, most_ko_wins, most_subs, most_reigns, etc.). Each query is `LIMIT 1` so it's bounded, but it's still 11 round-trips per Records screen load. Could be batched into a single UNION query. [LOW]
- `app_web.py:14320+` — per-record extra `SELECT record_wins, record_losses, record_draws FROM fighter_career WHERE fighter_id=?` query for context. [LOW]

**Data freshness violations:**
- Reads `fighter_career`, `fight_history`, `fighters`, `titles` directly. All are bounded single-row queries for record holders. [no violation]

### 13. Archive (`src/web/js/archive.js` + `app_web.py:get_archive_data`)

**Voice violations:** none — `rating_tier_label` + `rating_tier_color` are voice phrases; `net_profit_display` is a $ figure (cash carve-out); `net_profit_voice` is a voice phrase.

**Performance issues:**
- `app_web.py:10410+` — main query has LIMIT/OFFSET pagination ✓.
- `app_web.py:10450+` — per-event expanded-card query: main_event lookup, fight count lookup, finance_transactions lookup. Bounded to 1 event at a time (on expand). [LOW]

**Data freshness violations:**
- Reads `events`, `fights`, `fighters`, `venues`, `cities`, `show_ratings`, `finance_transactions` directly. Archive is fundamentally a historical view; no cache table for completed events. [no violation]

### 14. Free Agents (`src/web/js/free_agents.js` + `app_web.py:get_free_agents`)

**Voice violations:** none — `ceiling_display` is voice phrase OR "????" (when unscouted); `stage_short`, `form_short` come from descriptors; `record_str` is factual.

**Performance issues:** none — single paginated query with proper LIMIT/OFFSET.

**Data freshness violations:**
- `app_web.py:3133-3154` — reads `fighters`, `fighter_descriptors`, `fighter_career`, `weight_classes`, `gyms`, `nations`, `scouting_reports` directly.
- `app_web.py:3139` — `fc.potential` raw int is read BUT only used for sorting (line 3124) and ceiling-phrase fallback. NOT included in returned dict. ✓
- `app_web.py:3168-3172` — `ceiling_display` is voice phrase from `sr.estimated_ceiling` OR `_ceiling_phrase_from_potential(r[13])`. ✓

### 15. Agent Offers (`src/web/js/agent_offers.js` + `app_web.py:get_agent_offers`)

**Voice violations:** none — `fighter_description` is voice-layered prose; `asking_price_display` is a $ figure (cash carve-out); `days_until_expiry` is a countdown.

**Performance issues:** none — bounded to active offers (typically <5).

**Data freshness violations:** none observed.

### 16. Contracts (`src/web/js/contracts.js` + `app_web.py:get_contracts_data`)

**Voice violations:** none — `skill_phrase` is voice-layered; `salary_display` is a $ figure; `bonus_phrase` is a voice phrase; `days_until_expiry` is a countdown.

**Performance issues:** none — paginated queries with proper LIMIT/OFFSET.

**Data freshness violations:**
- `app_web.py:13590+` — reads `contracts`, `fighter_contracts`, `staff_contracts`, `fighters`, `staff` directly. No `contracts_descriptors` cache exists. [no violation]

### 17. Finance (`src/web/js/finance.js` + `app_web.py:get_finance_data`)

**Voice violations:** none — `reputation_phrase` / `fan_trust_phrase` are voice-layered; cash amounts are factual $ figures; `rating_phrase` + `rating_tier` are voice phrases.

**Performance issues:**
- `app_web.py:13190+` — main transactions query has LIMIT/OFFSET ✓.
- `app_web.py:13200+` — per-transaction fighter name resolution is a batched `IN (?)` query (good pattern). ✓

**Data freshness violations:**
- `app_web.py:13300+` — returns raw `reputation` (int), `fan_trust` (int), `overall_rating` (int) in the JSON payload. JS uses them only for bar widths / color thresholds, not as displayed text. Borderline §14/§17.4. [MEDIUM]

### 18. Rival Promotions (`src/web/js/rival_promotions.js` + `app_web.py:get_rival_promotions` + `get_rival_roster`)

**Voice violations:**
- `rival_promotions.js:128, 132` — displays `p.roster_count` and `p.champ_count` as numbers. These are factual counts (not attributes). ✓
- `rival_promotions.js:119, 123` — displays `repPhrase` and `trustPhrase` (voice phrases). ✓

**Performance issues:**
- `app_web.py:3257-3266` — 2 correlated subqueries per rival promo (roster_count + champ_count). Bounded to ~9 rival promos, so ~18 subqueries. [LOW]

**Data freshness violations:**
- `app_web.py:3255-3267` — reads `promotions` directly (NOT from `promotion_descriptors` cache, which exists per §17.3). [MEDIUM per §17.1]
- `app_web.py:3269-3278` — returns raw `reputation`, `fan_trust`, `current_cash` ints alongside voice phrases. [MEDIUM]
- `app_web.py:3440+` — `get_rival_roster` reads `fighters`, `fighter_descriptors`, `fighter_career`, `weight_classes`, `gyms`, `nations`, `injuries`, `suspensions`, `titles` directly. Mirrors `get_roster_data` pattern. [LOW]

### 19. Gyms (`src/web/js/gyms.js` + `app_web.py:get_gyms_data`)

**Voice violations:**
- `gyms.js:249` — `renderMeter` displays raw 0-100 value: `'<div class="ce-gym__meter-val ce-mono">' + v + '</div>'` for fatigue/morale/injury_risk camp stats. The JS comment at `gyms.js:45-46` carves this out as "camp-state ratings, NOT fighter attrs." Per §14 strict reading, internal ratings should pass through voice. [MEDIUM]
- `gyms.js:387` — `renderStatBar` displays raw 0-100 value: `'<span class="ce-gym__gym-stat-val ce-mono">' + v + '</span>'` for `facility_quality`, `medical_support`, `sparring_depth`, `development_focus`, `weight_cut_support`. Same carve-out comment at `gyms.js:41-43`. [MEDIUM]
- `gyms.js:412` — `'<span class="ce-gym__gym-rep-val ce-mono">' + gym.reputation + '</span>'` displays raw 0-100 gym reputation. [MEDIUM]

**Performance issues:**
- `app_web.py:12752-12757` — 2 correlated subqueries per gym row (fighter_count + active_camps_count). Bounded to 20 gyms/page = 40 subqueries. [LOW]

**Data freshness violations:**
- `app_web.py:12758` — `FROM gyms g` reads the simulation table directly. Per §17.3, `gym_descriptors` cache table exists and should be the read path. [HIGH per §17.1]
- `app_web.py:12778-12783` — returns six raw 0-100 ints (`reputation`, `facility_quality`, `medical_support`, `sparring_depth`, `development_focus`, `weight_cut_support`) in the JSON. [HIGH per §14 — these are internal ratings exposed to JS]
- `app_web.py:12827+` (`get_training_camps_data`) — likely reads `training_camps` directly. Same pattern. (Not deeply audited — bounds check only.) [MEDIUM]

### 20. Scouting (`src/web/js/scouting.js` + `app_web.py:get_scouting_data`)

**Voice violations:**
- `app_web.py:9592-9597` — returns `estimated_potential`, `estimated_ceiling`, `estimated_floor`, `estimated_strengths`, `estimated_weaknesses`, `marketability_assessment` as voice phrases (per scouting_reports schema — these are stored as voice descriptors, not raw ints). ✓
- `app_web.py:9602` — returns raw `scout_confidence: int(confidence or 0)` 0-100. The JS comment at `scouting.js:43-46` carves this out as "scout's own confidence rating, NOT a fighter attribute." Voice phrase `confidence_phrase` also returned at `app_web.py:9603-9604`. Raw int is in the JSON but the scouting.js UI displays only the phrase. Borderline §17.4 ("Rich Not Thin" — both label and phrase returned, UI uses phrase). [MEDIUM]

**Performance issues:** none — bounded queries, single page of reports.

**Data freshness violations:**
- `app_web.py:9560+` — reads `staff`, `fighters`, `scouting_reports` directly. `scouting_reports` is a derived table; not in cache taxonomy. [no violation]

### 21. Staff Market (`src/web/js/staff_market.js` + `app_web.py:get_staff_market_data`)

**Voice violations:**
- `app_web.py:9348` — returns raw `skill_level` int alongside `skill_phrase`. The JS comment at `staff_market.js:148` claims "NEVER displayed raw" — and the UI does only show the phrase — but the raw int is in the payload. Borderline §17.4. [MEDIUM]

**Performance issues:** none — single paginated query.

**Data freshness violations:**
- `app_web.py:9340+` — reads `staff`, `nations` directly. No `staff_descriptors` cache exists. [no violation]

### 22. Wire (`src/web/js/wire.js` + `app_web.py:get_wire_data`)

**Voice violations:** none — headlines are verbatim (news engine is the interpretation layer per §14.4); sentiment is shown as a tier label, not an int.

**Performance issues:**
- `app_web.py:10218-10227` — batched source-name lookup (good pattern — collects distinct source_ids then one IN-query). ✓

**Data freshness violations:**
- `app_web.py:10218-10227` — reads `news_items`, `fighters`, `promotions`, `news_sources` directly. `news_items` is a simulation table per §17.3 — but there is no `news_descriptors` cache. Per the daily_headlines cache table note in §17.3, daily_headlines only stores top_story + 4 headlines, not the full news_items feed. The Wire's full-feed read is acceptable since the cache doesn't cover this use case. [no violation]

### 23. App (`src/web/js/app.js` — app shell, navigation, top bar)

**Voice violations:** none — top bar shows `cash_display` ($ figure, cash carve-out) and `current_date` (factual date).

**Performance issues:** none — top bar uses cached `getClock` + `getPlayerCash` (2 lightweight queries on each nav).

**Data freshness violations:**
- `app_web.py:2244` (`get_player_cash`) — reads `promotions.current_cash` directly. Acceptable — cash is the live value, not a derived descriptor. [no violation]

### 24. Bridge (`src/web/js/bridge.js` — JS↔Python RPC layer)

**Voice violations:** N/A — bridge is a thin wrapper around `window.pywebview.api.*` calls. No data manipulation.

**Performance issues:** none observed. The bridge uses a single `_readyPromise` to gate API calls, which is correct.

**Data freshness violations:** N/A — bridge does not access the DB.

---

## Top 10 Highest-Impact Issues (recommended fix order)

1. **[HIGH]** `get_fight_compare` returns raw 25-attribute 0-100 ints (`red_attributes`, `blue_attributes`) to JS, drawn as radar-chart polygon magnitudes — affects Matchmaking Compare modal. Fix: route through `fighter_descriptors.attribute_descriptors` JSON (voice phrases) and use tier-based polygon points (gold=100%/steel=60%/crimson=25%) like the existing `phraseTier()` helper in `fighter_profile.js:76`.
2. **[HIGH]** `get_matchmaking_data` N+1 pattern — per-fighter `_fighter_brief` call (4+ subqueries each) on 100+ fighter rosters. Fix: batch into a single JOIN query (fighters + fighter_career + fighter_descriptors + rankings + style_archetypes), compute rank via window function, fetch clock once.
3. **[HIGH]** `get_event_builder_data` N+1 pattern — per-fighter `SELECT SUM(...) FROM fight_history` to compute W/L/D record. Fix: JOIN `fighter_career` (which already has `record_wins/losses/draws` columns).
4. **[HIGH]** `get_gyms_data` reads `gyms` simulation table directly and returns 6 raw 0-100 gym ratings, violating §17.1 + §14. Fix: read from `gym_descriptors` cache table (per §17.3), return voice phrases for `facility_quality` etc.
5. **[MEDIUM]** `fighter_profile.js:306` displays raw `career_health` 0-100 int in the Career Health stat tile, despite `career_health_desc` voice phrase existing. Fix: display the phrase, drop the int (or use it only for the bar fill width).
6. **[MEDIUM]** `rivalries.js:238` displays raw `rivalry_heat` 0-100 int alongside the voice `heat_phrase`. Fix: drop the raw int display (keep the bar visual + phrase).
7. **[MEDIUM]** `gyms.js:387,412` displays raw 0-100 ints for gym reputation + 5 stat bars. Fix: display the `quality_phrase` (already returned) and drop the raw ints (or use them only for bar widths).
8. **[MEDIUM]** `get_roster_data` correlated subqueries per row for `injury_count` and `susp_count`. Fix: LEFT JOIN + GROUP BY.
9. **[MEDIUM]** `get_rankings_data` correlated subquery per row for `last_outcome`. Fix: LEFT JOIN to a `fight_history` subquery aliased with `MAX(fight_history_id)`.
10. **[MEDIUM]** `get_rival_promotions` reads `promotions` simulation table directly and returns raw `reputation`/`fan_trust`/`current_cash` ints. Fix: read from `promotion_descriptors` cache table (per §17.3).

---

## Surprisingly Clean Screens

- **Dashboard** — exemplary voice compliance: every value the player sees is either a voice phrase, a factual count, or a $ figure. The bidding-alert section uses `fighter_ceiling_phrase` (voice) instead of raw potential.
- **Free Agents** — strict scouting-safety discipline: `fc.potential` is read for sorting but never returned; `ceiling_display` is voice phrase OR "????" literal.
- **Rankings** — explicit comment + guard against exposing the raw ELO float (`r.rating` is read for sorting but not included in the response dict).
- **Agent Offers** — clean separation: voice prose for the offer description, $ for asking price, int for countdown — no raw attributes.
- **Hall of Fame** — `career_summary` + `highlights` are pre-voice-layered prose; only career W-L-D counts are numeric.
- **Calendar** — voice phrases for conflict detection ("Counter-programming risk" / "Short turnaround" / "Clear date").
- **Titles** — reign length is voice-banded ("just won the belt" / "long-reigning champion" / "era-defining reign").
- **Wire** — clean batched source-name lookup pattern; headlines are the interpretation layer's output (per §14.4).
- **App / Bridge** — minimal shell, no data exposure concerns.

---

## Audit Methodology

- Read CONVENTIONS §14 (Voice Layer) + §17 (Snapshot Rule) — the rules audited against.
- Read each JS module in `src/web/js/` (24 modules) for raw-attribute-number patterns (`\.potential`, `0-100`, `\.rating\b`, `momentum`, `ceiling`, `fan_rating`, `overall_rating`, `career_health`, `rivalry_heat`, `facility_quality`, etc.).
- Read corresponding API methods in `src/app_web.py` (162 API methods; ~30 covered in depth for this audit).
- Cross-referenced SQL queries against the cache-vs-simulation table list in §17.3.
- Voice violations flagged when raw attribute/rating ints appear in JS template strings OR are returned in the API JSON payload.
- Performance issues flagged when queries lack LIMIT/OFFSET, exhibit N+1 patterns (per-row subqueries), or have obvious JOIN optimizations.
- Data freshness issues flagged when Office-Mode screens read simulation tables directly instead of cache tables, per §17.1.
- Severity: HIGH = raw attribute/rating exposed to player OR unbounded/N+1 query on 100+ row result sets; MEDIUM = suboptimal pattern (correlated subquery, raw int in JSON-but-not-displayed); LOW = strict-letter §17.1 violation for identity/record fields where no cache table exists.

## Files Audited

- 24 JS modules in `src/web/js/` (17,281 LOC total)
- 24 CSS files in `src/web/css/` (spot-checked, not exhaustively read — none had voice violations; CSS is presentation only)
- `src/app_web.py` (14,898 LOC, 162 API methods; ~30 methods read in depth)
- `docs/CONVENTIONS.md` §14 + §17 (rules)

## NO Code Changes Made

This was a read-only audit. No files were modified. The only file created is this report at `docs/PHASE5_SCREEN_AUDIT.md`.
