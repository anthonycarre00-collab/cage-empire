# CAGE EMPIRE — Decision→Consequence Chains (HW4.5)

> **Status:** Canonical — defines the formal cause→effect chains that
> HW6.7 (player agency test) verifies.
> **Last updated:** 2026-08-14 (HW10.2).
> **See also:** `docs/Hardening_Phase.md` §HW4.5, `scripts/test_decision_chains.py`.

## Purpose

Per GPT's W15 feedback: "Player decisions must have **meaningful,
traceable** consequences. The player should be able to take an action
and LATER see the downstream effects — both in the world state and in
the narrative."

This document defines the 10 formal decision→consequence chains (one
per `decision_type` in `player_decisions.ALL_TYPES`). Each chain
specifies:

1. **Trigger** — the player action that starts the chain.
2. **Immediate effect** — what happens synchronously in the same
   transaction (DB writes, event-bus publishes).
3. **Delayed effect** — what happens on subsequent ticks (subscribers
   that react, news that fires, state that changes).
4. **Narrative echo** — how the decision surfaces back to the player
   later (echoes engine, news items, dashboard chips).
5. **Test hook** — the assertion(s) `test_decision_chains.py` makes
   to verify the chain is wired end-to-end.

The chains are the **contract** between the player-action layer
(`app_web.py` API methods) and the simulation layer (event-bus
subscribers + interpretation layer). If a chain breaks (a subscriber
stops firing, a news item stops being written, an echo stops
surfacing), the test catches it.

---

## Chain 1: `sign` (sign a free agent)

**Trigger:** Player clicks "Sign" on a free agent in the Free Agents
screen. `app_web.sign_free_agent` → `contracts.sign_free_agent` →
`log_decision(TYPE_SIGN, target_fighter_id=X)`.

**Immediate effect (same transaction):**
- `fighters.current_promotion_id` updated to player's promo.
- `contracts` row INSERTed (12-month exclusive, salary per negotiation).
- `fighter_career.contract_status` updated to 'active'.
- Event bus publishes `FIGHTER_SIGNED` with `fighter_id`, `promotion_id`.

**Delayed effect (next tick + beyond):**
- `news.generate_signing_news` (subscribes to `FIGHTER_SIGNED`) writes
  a SIGNIFICANT news item: "Alpha Combat signs [Fighter Name]".
- `rivalries._check_social_beefs` may create a `callout` rivalry if
  the signed fighter has beef with an existing roster member.
- The signed fighter becomes eligible for `schedule_next_event` (next
  event card may include them).
- `morale._process_tick` applies a +5 morale boost to the signed
  fighter (relief of finding a new home).

**Narrative echo:**
- `echoes_engine` surfaces a `signing_echo` on the next daily pass:
  "You signed [Fighter] on [Date] — they've since [record since
  signing]".
- The Fighter Profile's "Your History with [Fighter]" section shows
  the sign decision as the first entry.

**Test hook:** `test_decision_chains.py::test_sign_chain` — signs a
free agent, advances 1 tick, asserts: contract row exists, FIGHTER_SIGNED
fired, signing news written, signing_echo queued.

---

## Chain 2: `cut` (release a fighter)

**Trigger:** Player clicks "Release" on a fighter in the Roster.
`app_web.cut_fighter` → `contracts.release_fighter` →
`log_decision(TYPE_CUT, target_fighter_id=X)`.

**Immediate effect:**
- `fighters.current_promotion_id` set to NULL.
- `contracts` row UPDATEd to status='terminated'.
- `fighter_career.contract_status` updated to 'free_agent'.
- Event bus publishes `FIGHTER_RELEASED` (no subscriber currently —
  future hook for rival AI poaching).

**Delayed effect:**
- `news.generate_release_news` writes a MAJOR news item: "[Fighter]
  released from Alpha Combat".
- `morale._process_tick` applies a -10 morale penalty to the released
  fighter (uncertainty of free agency).
- The released fighter becomes available in the Free Agents screen for
  rival promos to sign.
- If the fighter was a champion, the title is vacated
  (`titles.current_champion_fighter_id` set to NULL).

**Narrative echo:**
- `echoes_engine` surfaces a `cut_echo` on the next daily pass:
  "You released [Fighter] on [Date] — they've since [signed with RFL
  / retired / remained unsigned]".

**Test hook:** `test_decision_chains.py::test_cut_chain` — cuts a
fighter, advances 1 tick, asserts: contract terminated, release news
written, cut_echo queued.

---

## Chain 3: `book` (book a fight)

**Trigger:** Player clicks "Book Fight" in the Event Builder.
`app_web.book_fight` → `log_decision(TYPE_BOOK, target_fighter_id=X,
target_event_id=E)`.

**Immediate effect:**
- `fights` row INSERTed with the two fighter IDs + event_id.
- `fight_participants` rows INSERTed (2 rows, red + blue corner).
- `event_cards` row INSERTed (card_position, card_tier).
- `training_camps` rows INSERTed for both fighters (start_date=today,
  end_date=event_date).
- `punditry.generate_matchup_analysis` writes a `matchup_analyses` row
  (predicted_winner, method, confidence).
- HW9.2: `news.generate_fight_preview_memory_news` writes a
  memory_resurfacing news item if the two fighters have history.

**Delayed effect:**
- On the event_date tick: `fight_engine.resolve_next_fight` resolves
  the fight (writes fight_history, updates rankings, possibly changes
  title, writes fight news + commentary).
- `finance.process_event_transactions` writes purse + bonus + ticket
  sales rows for the event.
- `show_rating.calculate_show_rating` writes a show_ratings row.
- If the fight was a title fight + the title changed hands:
  `FIGHTER_RETIRED` may fire if the loser is past decline age + the
  loss triggers retirement.

**Narrative echo:**
- `echoes_engine` surfaces a `booking_echo` on the next daily pass:
  "You booked [Fighter A] vs [Fighter B] on [Date] — result:
  [winner] won by [method] in round [N]".

**Test hook:** `test_decision_chains.py::test_book_chain` — books a
fight, advances to event_date, resolves, asserts: fight resolved,
finance rows written, show_rating row written, booking_echo queued.

---

## Chain 4: `scout` (assign a scout to a fighter)

**Trigger:** Player assigns a scout to a fighter in the Scouting
screen. `app_web.assign_scout` → `log_decision(TYPE_SCOUT,
target_fighter_id=X)`.

**Immediate effect:**
- `scouting_assignments` row INSERTed (scout_id, target_fighter_id,
  start_date, status='active').

**Delayed effect (7+ days later):**
- `scouting._check_scouting_assignments` generates a `scouting_reports`
  row when 7+ days have elapsed (report_date, projected_potential,
  strengths, weaknesses).
- `news.generate_scout_report_news` writes a ROUTINE news item:
  "Scouting report filed on [Fighter]".
- The scouting report becomes visible in the Fighter Profile's
  "Scouting" tab.

**Narrative echo:**
- `echoes_engine` surfaces a `scouting_echo` on the next daily pass
  after the report is generated: "You scouted [Fighter] on [Date] —
  report: [potential phrase], [strength phrase]".

**Test hook:** `test_decision_chains.py::test_scout_chain` — assigns
a scout, advances 8 days, asserts: scouting_report row written, scout
news written, scouting_echo queued.

---

## Chain 5: `hire_staff` (hire a staff member)

**Trigger:** Player hires a staff member in the Staff Market.
`app_web.hire_staff` → `log_decision(TYPE_HIRE_STAFF,
target_staff_id=X)`.

**Immediate effect:**
- `staff` row UPDATEd (current_promotion_id = player's promo).
- `staff_contracts` row INSERTed (12-month, salary per negotiation).
- Event bus publishes `STAFF_HIRED` (no subscriber currently — future
  hook for staff morale).

**Delayed effect:**
- `news.generate_staff_hire_news` writes a ROUTINE news item:
  "Alpha Combat hires [Staff Name] as [role]".
- The staff member becomes available for assignment to a fighter or
  gym via `assign_staff`.

**Narrative echo:**
- (Currently no echo — staff decisions don't surface in echoes_engine.
  Future enhancement: add `staff_hire_echo`.)

**Test hook:** `test_decision_chains.py::test_hire_staff_chain` —
hires a staff member, advances 1 tick, asserts: staff_contracts row
written, hire news written.

---

## Chain 6: `fire_staff` (terminate a staff contract)

**Trigger:** Player fires a staff member. `app_web.fire_staff` →
`log_decision(TYPE_FIRE_STAFF, target_staff_id=X)`.

**Immediate effect:**
- `staff_contracts` row UPDATEd to status='terminated'.
- `staff.current_promotion_id` set to NULL.

**Delayed effect:**
- `news.generate_staff_fire_news` writes a ROUTINE news item.

**Narrative echo:** (none currently)

**Test hook:** `test_decision_chains.py::test_fire_staff_chain`.

---

## Chain 7: `assign_staff` (assign a staff to a fighter/gym)

**Trigger:** Player assigns a coach to a fighter or gym.
`app_web.assign_staff` → `log_decision(TYPE_ASSIGN_STAFF,
target_staff_id=X, target_fighter_id=Y)`.

**Immediate effect:**
- `staff_assignments` row INSERTed (staff_id, fighter_id, role,
  start_date).
- The fighter's `current_coach_id` updated.

**Delayed effect:**
- The coach's `coaching_rating` modulates the fighter's next training
  camp gains (`training_svc._check_training_camps` reads
  `staff.coaching_rating`).
- `news.generate_staff_assign_news` writes a ROUTINE news item.

**Narrative echo:** (none currently)

**Test hook:** `test_decision_chains.py::test_assign_staff_chain`.

---

## Chain 8: `set_ticket_price` (financial lever)

**Trigger:** Player adjusts ticket price in the Finance screen.
`app_web.set_ticket_price` → `log_decision(TYPE_SET_TICKET_PRICE,
context={'old_price': X, 'new_price': Y})`.

**Immediate effect:**
- `player_settings.ticket_price` UPDATEd.
- No event published (financial levers don't fire events — they're
  read by the next event's finance calculations).

**Delayed effect:**
- On the next event resolved: `finance.process_event_transactions`
  reads the new ticket_price + applies the price-elasticity demand
  curve (higher price → fewer tickets sold, but more revenue per
  ticket; lower price → more tickets, less per ticket).
- `news.generate_finance_news` may write a ROUTINE news item if the
  price change was significant (>20% delta).

**Narrative echo:** (none — financial decisions don't surface in
echoes. The Finance screen itself shows the history.)

**Test hook:** `test_decision_chains.py::test_set_ticket_price_chain`
— sets a new ticket price, runs an event, asserts: ticket_sales row
reflects the new price × demand.

---

## Chain 9: `set_marketing` (financial lever)

**Trigger:** Player adjusts marketing spend. `app_web.set_marketing`
→ `log_decision(TYPE_SET_MARKETING, context={'old': X, 'new': Y})`.

**Immediate effect:**
- `player_settings.marketing_spend` UPDATEd.

**Delayed effect:**
- On the next event: `finance.process_event_transactions` applies the
  marketing-return curve (diminishing returns — each additional $X
  yields less + less awareness boost).
- `show_rating.calculate_show_rating` factors marketing into the
  attendance calculation.

**Narrative echo:** (none)

**Test hook:** `test_decision_chains.py::test_set_marketing_chain`.

---

## Chain 10: `negotiate_contract` (re-negotiate a fighter's contract)

**Trigger:** Player re-negotiates a fighter's contract.
`app_web.negotiate_contract` → `log_decision(TYPE_NEGOTIATE_CONTRACT,
target_fighter_id=X, context={'new_salary': Y})`.

**Immediate effect:**
- `contracts` row UPDATEd (salary, end_date extended).
- `fighter_career.contract_status` confirmed 'active'.

**Delayed effect:**
- `news.generate_contract_news` writes a ROUTINE news item:
  "[Fighter] re-signs with Alpha Combat on improved terms".
- `morale._process_tick` applies a +5 morale boost (the fighter feels
  valued).

**Narrative echo:** (none currently — could add a `contract_echo`.)

**Test hook:** `test_decision_chains.py::test_negotiate_contract_chain`.

---

## Chain verification (HW6.7)

`scripts/test_decision_chains.py` (HW4.5) verifies each chain's
immediate + delayed effects fire. `scripts/test_player_agency.py`
(HW6.7) goes further: it verifies the **narrative echo** surfaces
back to the player (the dashboard's ECHOES section shows the decision
within 1 daily pass, and the Fighter Profile's "Your History" section
shows the decision in the timeline).

If a chain breaks, the test names the broken link:
- "sign_chain: FIGHTER_SIGNED not published" → the API method stopped
  publishing the event.
- "sign_chain: signing news not written" → the news subscriber stopped
  firing or the cap suppressed it.
- "sign_chain: signing_echo not queued" → the echoes engine stopped
  surfacing the decision.
