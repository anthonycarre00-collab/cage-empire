> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — UI Implementation Plan v3

> **Status:** PLANNING. Awaits supervisor approval before coding.
> **Source:** User testing feedback + design doc review + codebase audit by Explore subagent.
> **Supersedes:** UI_FIX_PLAN_2.md (partially — some fixes from that plan are done, some need rework).

## Root Causes Found

### 1. Hyperlinks don't work (user issue #1)
**Root cause:** FighterTable widget only binds `<Button-1>` on the ROW FRAME, not on the individual LABEL widgets inside each cell. Tk does NOT propagate mouse events from child widgets to parent frames by default. So clicking on the TEXT of any non-Name cell (Age, WC, Stage, Form, Record — 5 of 6 columns) silently does nothing. Only the Name column works (because HyperlinkLabel has its own binding).

**Fix:** Bind `<Button-1>`, `<Enter>`, `<Leave>` on the label widgets too (with `add="+"` so HyperlinkLabel's own handlers aren't displaced). ~15 LOC.

### 2. Free Agents table is still ttk.Treeview (user issue #4)
**Root cause:** The Phase 3 subagent migrated Roster to FighterTable but DIDN'T migrate Free Agents. Free Agents still uses the old ttk.Treeview with its own column set, no HyperlinkLabels, no hover effect, no alternating colors. The two sister screens look completely different.

**Fix:** Migrate Free Agents to FighterTable with the same column layout + styling as Roster. Add the "Ceiling" column (renamed from "Potential"). ~200 LOC deleted, ~150 added.

### 3. Dashboard fighter names not clickable (user issue #2)
**Root cause:** The `fighter_id` data IS fetched for Top Story headlines, Other Headlines, and Fighter Watch cards — but it's never passed to the widget. All fighter names are plain `CTkLabel` instead of `HyperlinkLabel`. Only champion names got the HyperlinkLabel treatment.

**Fix:** Replace `CTkLabel` with `HyperlinkLabel` for all fighter name mentions on the Dashboard: Top Story, Other Headlines, Fighter Watch cards, Recent News. The data is already there — just wire it.

### 4. Roster has redundant tips + missing nationality (user issue #3)
**Root cause:** Two hint labels saying the same thing (one inline, one at the bottom). No nationality column in the table.

**Fix:** Collapse to one hint (or remove entirely — user said "remove it"). Add nationality column (from `fighters.birth_nation_id` → `nations.name` → abbreviate to 3-letter code). Rebalance column widths.

### 5. Visual appeal is "generic crap" (user issue #5)
**Root cause:** The UI uses flat dark backgrounds with no texture, no visual hierarchy beyond text size, and the "Cage Empire voice" is applied to labels but not to the VISUAL design (layout, spacing, card styling, accent colors).

**Fix (sparing, per design docs):**
- Add subtle gradient/texture to the top bar (deep charcoal with a faint crimson-to-black gradient)
- Add a 2px crimson accent line under the top bar (separates it from content)
- Add gold left-border (2px) to section title rows on the Dashboard
- Use `bg_surface_elevated` for ALL cards (currently mixed with `bg_surface`)
- Add a subtle background texture image (very low opacity) to the main content area — a faint octagon grid pattern at 3-5% opacity
- Increase card padding (20px internal) and card spacing (16px between cards)
- Use the promotion logo as a faded background watermark on the Dashboard (10% opacity behind the "The Empire" section)

## Prioritized Fix List

### P0 — Critical (broken core UX)

| # | Fix | File(s) | Effort | Risk |
|---|---|---|---|---|
| P0-1 | Migrate Free Agents to FighterTable | free_agents.py | M | Medium |
| P0-2 | Fix FighterTable label-cell click bindings | fighter_table.py | S | Low |

### P1 — High (broken hyperlinks where data exists)

| # | Fix | File(s) | Effort | Risk |
|---|---|---|---|---|
| P1-1 | Dashboard Fighter Watch → HyperlinkLabel | dashboard.py | S | Low |
| P1-2 | Dashboard Top Story → HyperlinkLabel | dashboard.py | S | Low |
| P1-3 | Dashboard Other Headlines → HyperlinkLabel | dashboard.py | S | Low |
| P1-4 | Dashboard Recent News → query + HyperlinkLabel | dashboard.py | M | Medium |

### P2 — Medium (consistency + visual polish)

| # | Fix | File(s) | Effort | Risk |
|---|---|---|---|---|
| P2-1 | Roster: remove redundant hints, add nationality column, rebalance | roster.py | S | Low |
| P2-2 | Add visual texture: top bar gradient, accent lines, card borders, octagon grid background | theme.py + app.py + screens | M | Low |
| P2-3 | Delete legacy Treeview code (~600 LOC dead code) | roster.py + free_agents.py | S | Medium |
| P2-4 | HyperlinkLabel hover color from theme (not hardcoded) | hyperlink.py + theme.py | S | Low |

### P3 — Low (polish + Soul alignment)

| # | Fix | File(s) | Effort | Risk |
|---|---|---|---|---|
| P3-1 | "View Profile →" link on Fighter Watch cards | dashboard.py | S | Low |
| P3-2 | Dashboard "What's Coming" anticipation card | dashboard.py | M | Medium |
| P3-3 | FighterTable keyboard arrow navigation | fighter_table.py | M | Medium |

## Execution Order

1. **P0-2** first (15 LOC, fixes clicks on 5/6 columns in both screens)
2. **P0-1** (Free Agents migration — biggest consistency win)
3. **P1-1 through P1-4** (all same pattern: replace CTkLabel with HyperlinkLabel)
4. **P2-1** (remove hints, add nationality, rebalance)
5. **P2-2** (visual texture — sparingly)
6. **P2-3 + P2-4** (cleanup)
7. **P3** (polish, after user tests again)

## Visual Texture Plan (sparing, per design docs)

Per GUI_PLAN §3.1: "Bloomberg Terminal meets ESPN scoreboard" — not a fight poster, not an arcade screen.

- **Top bar:** Deep charcoal `#0f1115` with a subtle 2px crimson line at the bottom edge
- **Section titles:** Gold left-border accent (2px CTkFrame, `fg_color=gold`)
- **Cards:** All use `bg_surface_elevated` (`#232730`) with `corner_radius=8` and `border_width=1` + `border_color=bg_border`
- **Card spacing:** 16px between cards (was inconsistent)
- **Card padding:** 20px internal (was 15px)
- **Main content background:** Solid `#0f1115` — NO texture image (keeps it clean, avoids moiré on different screen sizes)
- **Promotion watermark:** The player's promotion logo at 10% opacity, centered, behind the Dashboard's "The Empire" section (very subtle — uses PIL to blend at low alpha)

This gives visual depth without being OTT or garish — consistent with the design docs' "calm, data-dense, institutional" Office Mode.

## Wiring Map (all navigation paths)

| From | Click target | Action | Back goes to |
|---|---|---|---|
| Roster table | Fighter name (HyperlinkLabel) | set_fighter_id + navigate to profile | Roster |
| Roster table | Row (any cell) | Select row + enable View Profile button | — |
| Roster table | View Profile button | set_fighter_id + navigate to profile | Roster |
| Free Agents table | Fighter name (HyperlinkLabel) | set_fighter_id + navigate to profile | Free Agents |
| Free Agents table | Sign button | sign_free_agent + refresh_all | — |
| Dashboard | Top Story headline | set_fighter_id + navigate to profile | Dashboard |
| Dashboard | Other Headline item | set_fighter_id + navigate to profile | Dashboard |
| Dashboard | Fighter Watch card name | set_fighter_id + navigate to profile | Dashboard |
| Dashboard | Fighter Watch "View Profile →" | set_fighter_id + navigate to profile | Dashboard |
| Dashboard | Champion name | set_fighter_id + navigate to profile | Dashboard |
| Dashboard | Recent News fighter name | set_fighter_id + navigate to profile | Dashboard |
| Fighter Profile | Back button | go_back() | (whatever they came from) |

All paths use the nav back-stack (Phase 1 Fix 14). The Fighter Profile's back button calls `state.go_back()` which pops the stack and returns to the referrer screen.
