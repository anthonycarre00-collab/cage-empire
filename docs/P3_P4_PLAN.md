> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# P3+P4 Plan: Agent Offers + Record Book (final 2 screens)

> **Status:** ACTIVE — eliminates the last 2 placeholder screens.
> **Source:** `docs/COMPREHENSIVE_REVIEW.md` P3 + P4

---

## P3: Agent Offers — `agent_offers` (dark system → expose to UI)

### Backend (exists, 893 lines)
`src/agent_offers.py` — agents offer the player unknown fighters (mystery-box gamble). The player sees a vague description but NOT the fighter's name or attributes — they must decide whether to sign based on limited info. This is the Talent Hunter fantasy's highest-dopamine moment.

- Table: `agent_offers` (5 rows currently)
- Columns: offer_id, promotion_id, fighter_id, offer_date, offer_type, asking_price, fighter_description, is_resolved, resolution, resolution_date, expires_date
- Key functions: `get_active_offers(conn, promotion_id)`, `resolve_offer(conn, offer_id, accept=True)`, `register_subscribers()` (subscribes to TICK_ADVANCED — generates offers weekly)
- The fighter_description is a voice-layer vague description: "A 19-year-old from Brazil. Reportedly shows elite-level striking instincts." — does NOT reveal the fighter's name or raw attributes.

### API needed
- `get_agent_offers()` — returns active offers for player's promo
- `resolve_agent_offer(offer_id, accept)` — accept or decline

### UI
- Section header: "AGENT OFFERS" (gold accent) + subtitle "X active offers"
- Offer cards: fighter_description (the vague scouting report), asking_price, offer_type chip ("Mystery Prospect" / "Established Fighter" / "Comeback Veteran"), expires_date (countdown)
- "Sign for $X" button (accepts — reveals the fighter's identity!) 
- "Pass" button (declines)
- When accepted: show a reveal animation/toast: "It's... [Fighter Name]!" → navigates to Fighter Profile
- Empty state: "No agents have come knocking. They will when the market moves."

## P4: Record Book — `records` (build from scratch)

### Backend (none — build from fight_history + fighter_career)
No table needed — compute from existing data on the fly.

### API needed
- `get_records_data()` — returns all-time records computed from DB

### Records to compute
1. Most wins (all-time)
2. Most KO/TKO wins
3. Most submission wins
4. Most title reigns
5. Most title defenses
6. Longest win streak
7. Most fights (total)
8. Best win percentage (min 10 fights)
9. Most recent champions (active title holders)
10. Oldest active fighter
11. Youngest active fighter
12. Most rivalries (fighter with most active rivalries)

### UI
- Section header: "THE RECORD BOOK" (gold accent) + subtitle "All-time leaders"
- Grid of record cards: each card shows record title, fighter name (clickable → Fighter Profile), value (big number), context phrase
- Paginated or just a long scroll
- Empty state: "The record book is being written. Give it time."
