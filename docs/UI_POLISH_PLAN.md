# CAGE EMPIRE — UI Polish Plan (Issues from User Testing)

> **Status:** MUST FIX BEFORE building more screens.
> **Authored:** 2026-07-30. Based on user screenshot feedback + spec doc analysis.

---

## Issues Identified (from user feedback + screenshots + spec review)

### 1. Too much information shown — no hidden attributes/personality
**Problem:** Fighter Profile shows ALL 26 attributes + ALL 20 personality traits for every fighter. The spec says "3-5 hidden traits" and scouting should reveal info gradually. The player should NOT see everything immediately — that's the whole point of the scouting system.

**Spec guidance:**
- "3-5 hidden traits. That is enough to generate believable fight outcomes without making the game impossible to balance."
- "1-3 hidden story tags like gym_hero, bad_weight_cutter, silent_finisher, stirrer, glass_ego"
- Scouting is a core loop: "Scout fighters, prospects, and rivals"
- Information asymmetry is the fun: "Unknown fighters" is a key early-game state

**Fix:**
- Fighter Profile (for YOUR fighters): show top 5-8 attributes as voice descriptors + career phase + momentum. Hide the rest behind a "Full Stats" expandable section.
- Fighter Profile (for OTHER promotions' fighters / free agents): show EVEN LESS — only name, record, weight class, bio, and whatever scouting has revealed. Unscouted fighters show "Unknown" for most fields.
- Personality: show only 3-5 key traits (aggression, composure, discipline, marketability, fan_friendliness) as voice descriptors. Hide the rest.
- Add a "Scouting Report" section that shows what scouts have estimated (with uncertainty).

### 2. Men and women mixed together in roster
**Problem:** The Roster table shows male and female fighters mixed together. They should be separated — male weight classes and female weight classes are different divisions.

**Fix:**
- Add a gender filter to the Roster (All / Male / Female)
- Default to the player's promotion's dominant gender (or show tabs: "Male Roster" / "Female Roster")
- Free Agents: same filter

### 3. No clickable links between roster names and fighter profiles
**Problem:** The roster table shows fighter names but clicking doesn't navigate to the Fighter Profile. (Note: the subagent implemented double-click navigation, but the user didn't discover it. Need single-click or a visible "View" button.)

**Fix:**
- Make fighter names clickable (single-click navigates to Fighter Profile)
- OR add a "View" button column in the table
- Make it OBVIOUS — add hover effect on names, or a visible button

### 4. No space for fighter images/portraits
**Problem:** The Fighter Profile has no placeholder for a portrait image. The spec says "Portrait/source image reference" is part of the fighter model, and "visual presentation for portraits and cards" is a key feature.

**Fix:**
- Add a portrait placeholder (150x150px) at the top-left of the Fighter Profile
- Use a default silhouette image (we have `src/ui/assets/portraits/default/`)
- When portrait images are available, load them from `data/portraits/<fighter_id>.png`

### 5. Ugly text/fonts with no capital letters
**Problem:** Text appears in lowercase or inconsistent capitalisation. Fonts look default/plain.

**Fix:**
- Ensure all voice phrases use Title Case or proper sentence capitalisation
- The voice.py descriptors should be checked — some may return lowercase
- Use the bundled Inter font properly (it IS bundled in assets/fonts/ but may not be registering on Windows)
- Add font registration that works on Windows (the current _register_fonts may fail silently)

### 6. No icons, images, or backgrounds
**Problem:** The UI is pure text — no visual interest. The spec says "polished, with fighter profiles, rich event narration, social media, news, and visual presentation."

**Fix:**
- Add the supervisor's logo to the top bar (it's in `src/ui/assets/logo/`)
- Add subtle background texture or gradient to panels
- Add status icons (champion = gold star, injured = red cross, etc.) — we have an icon system planned but not generated yet
- Use the supervisor's logo on the promotion selection screen

### 7. Other layout issues
- Top bar logo is showing as text "CAGE EMPIRE" instead of the actual logo image
- Dashboard sections may need better spacing/alignment
- News ticker text may still overflow

---

## Execution Plan

### Phase A: Fix existing screens (Dashboard, Roster, Fighter Profile, Free Agents)
1. Fix font registration for Windows (so Inter/JetBrains Mono actually load)
2. Add logo image to top bar
3. Fix capitalisation in voice descriptors
4. Add gender filter to Roster + Free Agents
5. Make roster names clickable → Fighter Profile (single-click)
6. Add portrait placeholder to Fighter Profile
7. Hide full attributes behind "Show Full Stats" toggle
8. Show limited info for unscouted fighters
9. Add subtle background/panel styling

### Phase B: Then continue with new screens (6.6+)
Only after Phase A is tested and working.
