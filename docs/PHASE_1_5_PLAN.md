> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — Phase 1.5: World DB Data Reconciliation Plan

> **Status:** Awaiting supervisor sign-off. 19 fixes (4 critical + 15
> lower-priority) identified by the 2nd-opinion audit + user
> requirements. Delegated to subagents in 3 groups (A/B/C).
> **Schema impact:** One MINOR bump for Fix C6 (staff.gym_id column,
> 3.8.0 → 3.9.0). All other fixes are data-only.
> **Prerequisite:** Phase 1 complete (✅ at commit c287616).

---

## 0. Context

The 2nd-opinion audit found the world DB is 70% there but has 4
critical bugs + 15 lower-priority gaps. The user also added 2
specific requirements:
1. **Gender separation** — no mixed-gender fights can be booked
   (verified: 0 exist in history, but matchmaking needs a gender
   check added)
2. **Remove future events** — game logic will gen new events, so
   the 848 future-dated "completed" events should be deleted, not
   re-dated

---

## Group A: Critical Data Reconciliation (9 fixes, no schema changes)

These are SQL data fixes against the existing world DB. No new
code modules needed — just a reconciliation script.

### A1: Remove future-dated "completed" events [CRITICAL]
- **Problem:** 848 events dated 2026-07-21 to 2026-12-28 marked
  "completed" — they're in the future relative to sim start
  (2026-07-20). Game logic will gen new events, so these should
  be DELETED (user's instruction).
- **Fix:** DELETE all events (+ their fights + fight_history +
  event_cards) where event_date > sim_start_date AND status =
  'completed'. Also delete orphaned fight_history rows.
- **Also:** Keep SCHEDULED future events (status='scheduled') —
  those are legitimately upcoming.

### A2: Recompute win_streak / loss_streak [CRITICAL]
- **Problem:** win_streak is capped at 6 for every fighter. 37%
  of fighters (1,461) have declared streaks off by >2 vs. computed
  reality from fight_history.
- **Fix:** For each active fighter with fight_history rows,
  recompute current win_streak and loss_streak by walking
  fight_history in reverse chronological order. Update
  fighter_career.win_streak + loss_streak.

### A3: Mark historical title fights [CRITICAL]
- **Problem:** is_title_fight=0 for ALL 34,419 fights. Champions
  claim 1-8 defenses but no actual title-bout rows exist.
- **Fix:** For each title's current champion, find their fight_history
  wins that occurred during their title reign (between
  champion_since_date and now). Mark a portion of those fights as
  is_title_fight=1 (up to title_defenses_count). This is
  approximate — we can't know exactly which fights were title
  bouts, but we can make the data internally consistent.

### A4: Fix rivalry fight counts [HIGH]
- **Problem:** 58 rivalries have fights_count=0 (purely synthetic).
  40 have fights_count=24-54 (impossibly high). Real MMA rivalries
  are 1-4 fights.
- **Fix:** For each rivalry, query fight_history for actual fights
  between the two fighters. Update fights_count, wins_a, wins_b,
  draws to match reality. If no actual fights exist, set
  fights_count=0 but keep the rivalry (it's a "declared" rivalry
  from social media callouts).

### A5: Backfill rankings.last_fight_date [MEDIUM]
- **Problem:** NULL for all 3,450 ranking rows.
- **Fix:** For each ranked fighter, find their most recent
  fight_history.event_date and update rankings.last_fight_date.

### A6: Backfill news_items.promotion_id [MEDIUM]
- **Problem:** NULL for all 431 news items.
- **Fix:** For each news item with an event_id, look up the event's
  promotion_id and update news_items.promotion_id. For news items
  with a fighter_id but no event_id, look up the fighter's
  current_promotion_id.

### A7: Link injuries to fights/events [MEDIUM]
- **Problem:** All 405 injuries have fight_id=NULL and event_id=NULL.
- **Fix:** For each injury, find the fighter's most recent fight
  before injury.start_date. If found, set injury.fight_id and
  injury.event_id. If no fight found (training injury), leave NULL
  but that's OK.

### A8: Remove catchweight/super-lightweight weight classes [HIGH]
- **Problem:** WC 14 (Catchweight 165), 15 (Catchweight 175), 16
  (Super Lightweight) are non-standard, have 0 fighters, and
  clutter the weight class list.
- **Fix:** DELETE these 3 weight classes from weight_classes.
  Also DELETE any titles for these WCs (if any exist). No fighters
  reference them (0 fighters).

### A9: Re-bias finish-round distribution [LOW]
- **Problem:** R1 25% / R2 15% / R3 60%. Real MMA has more R1
  finishes. R3 dominance suggests seed biased toward
  scheduled_rounds.
- **Fix:** For historical fights with a finish (not decision),
  redistribute some R3 finishes to R1/R2. This is cosmetic —
  update fights.finish_round for a subset of R3 finishes.
- **Defer?** This is LOW priority and cosmetic. May defer to
  Phase 2.

---

## Group B: Weight Classes + Gender + Fighters (4 fixes)

### B1: Populate 3 empty male weight classes [CRITICAL]
- **Problem:** Featherweight (WC 6), Bantamweight (WC 7), Flyweight
  (WC 8) — all male — have ZERO fighters. The male side ends at
  Lightweight.
- **Fix:** Generate ~150-200 fighters per empty WC (total ~500)
  using the existing fighter generation pipeline. Distribute across
  promotions proportional to existing roster sizes. Assign
  attributes from bio-driven assignment (same as the 4000 existing
  fighters). These need bios too — generate from templates (not
  supervisor profiles, since the supervisor's 4000 profiles don't
  include these WCs).
- **Also:** Create titles for these WCs across all 10 promotions
  (30 new titles). Seed initial rankings.

### B2: Re-roll 38 generic "Balanced" fighters [LOW]
- **Problem:** 38 "Balanced"-archetype fighters have attribute
  stdev < 2 (everything clustered 46-55). They're functionally
  generic.
- **Fix:** For each of these 38 fighters, re-roll their attributes
  with more variance (use the bio-driven assignment again, with
  higher random variance).

### B3: Fix 550 ghost-record free agents [HIGH]
- **Problem:** 550 active fighters have W/L records (e.g., 5-8-2)
  but ZERO rows in fight_history. Their records are fictional.
- **Fix:** Zero their records to 0-0-0 (set fighter_career.
  record_wins=0, record_losses=0, record_draws=0, win_streak=0,
  loss_streak=0). They're free agents with no pro fights — makes
  sense as unsigned prospects.

### B4: Add gender check to matchmaking [HIGH — user requirement]
- **Problem:** Matchmaking doesn't explicitly check gender. It
  relies on weight_class_id, which is gender-specific. But there's
  no defensive check.
- **Fix:** In services/matchmaking.py _pick_matchup (or wherever
  matchups are selected), add a gender check: both fighters must
  have the same gender. This is a code change, not a data fix.
  Add an assertion or explicit filter: `WHERE f.gender = ?
  (the first fighter's gender)`.

---

## Group C: Seed Missing Data + Schema (6 fixes)

### C1: Seed training_camps [MEDIUM]
- **Problem:** 0 rows. Schema exists (v2.5.0). The Soul document
  calls training-camp-based development a fantasy pillar.
- **Fix:** For each fighter with a scheduled fight (upcoming event),
  create a training_camps row. For historical flavor, create a
  few recent completed camps for random active fighters.

### C2: Seed suspensions [MEDIUM]
- **Problem:** 0 rows. Schema exists (v3.4.0).
- **Fix:** Seed 5-10 active suspensions (USADA-style, medical,
  behavioral) for random fighters. Include start_date, end_date,
  description. Write suspension news items.

### C3: Seed fighter_memory_links for HoF legends [HIGH]
- **Problem:** 0 rows. The Memory Engine is a Soul pillar (#4
  Legacy). Should have at least seeded some "remember when" links
  for the 60 HoF inductees.
- **Fix:** For each HoF inductee, create 1-2 memory links:
  - 'successor' links if a regen replacement exists (probably not
    at day 1)
  - 'style_echo' links to active fighters with the same style
    archetype (at least 1 per legend)
  - These will resurface in news when successors win titles

### C4: Seed show_ratings for historical events [LOW]
- **Problem:** 0 rows. Historical events have no quality ratings.
- **Fix:** For a sample of ~500 historical events, generate
  show_ratings (fan_rating, commercial_rating, excitement_rating,
  quality_rating, overall_rating, rating_description via voice
  layer). This gives the Past Events screen data to display.

### C5: Seed finance_transactions [LOW]
- **Problem:** 0 rows. Promotions have starting_cash but no
  transaction log.
- **Fix:** For each promotion, seed an opening balance transaction
  (type='opening_balance', amount=starting_budget). This gives the
  Finance screen a starting point.

### C6: Add staff.gym_id column + assign coaches [MEDIUM — schema bump]
- **Problem:** 300 coaches exist in staff but have no gym linkage.
  staff_contracts is empty. Gyms can't be linked to coaches.
- **Fix:** Add `staff.gym_id` column (INTEGER, nullable, FK to
  gyms). Schema bump 3.8.0 → 3.9.0 (MINOR). Write migration
  `_migrate_v3_9_0_add_staff_gym_id`. Assign each coach to a gym
  (match by nation_id if possible, else random).

---

## Execution Order

1. **Group A first** (data reconciliation — no schema changes, no
   new code, just SQL fixes against the world DB). Can be done in
   a single script: `scripts/reconcile_world_db.py`.
2. **Group B second** (weight classes + gender + fighters). B1
   (populate empty WCs) is the biggest — needs fighter generation.
   B4 (gender check) is a code change in matchmaking.
3. **Group C third** (seed missing data + schema). C6 (staff.gym_id)
   is the only schema bump — 3.8.0 → 3.9.0.

After each group: supervisor verification (all 39 tests pass,
forensic DB check passes, world DB intact).

---

## Gender Separation (user's specific requirement)

**Current state (verified):**
- weight_classes table has a `gender` column (male/female) ✓
- 0 mixed-gender fights in history ✓
- 0 fighters in wrong-gender weight class ✓

**What's missing:**
- Matchmaking doesn't explicitly check gender — it relies on
  weight_class_id being gender-specific. This works but is fragile.
- Fix B4 adds an explicit gender check to matchmaking as a
  defensive measure.

**No mixed-gender fights can be booked** after B4 — the matchmaking
code will filter by gender explicitly.
