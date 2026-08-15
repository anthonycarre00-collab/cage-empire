> ⚠️ **OBSOLETE** — This is a historical planning doc. The current source of truth is
> [`docs/Hardening_Phase.md`](Hardening_Phase.md) (the canonical hardening plan) +
> [`docs/CURRENT_SYSTEM_STATE.md`](CURRENT_SYSTEM_STATE.md) (what exists, what works,
> what's broken). This doc is preserved for historical context only.

---

# CAGE EMPIRE — UI Migration: CustomTkinter → pywebview + HTML/CSS

> **Status:** APPROVED by supervisor. Migration begins with Dashboard prototype.
> **Date:** 2026-08-02
> **Trigger:** CustomTkinter's `fg_color="transparent"` is NOT real transparency
   (CTkFrame._draw() always paints opaque). This fundamental limitation makes
   gradients, textures, and layering impossible. 15+ iterations produced 2.5/10
   visual quality. The user approved migration to pywebview + HTML/CSS.

## Architecture

```
┌─────────────────────────────────────────────┐
│  pywebview window (native desktop app)      │
│  ├── HTML/CSS/JS frontend (real CSS)        │
│  │   ├── CSS variables (theme system)       │
│  │   ├── Web fonts (Oswald, Inter, etc.)    │
│  │   ├── Real transparency, gradients       │
│  │   ├── Textures via CSS background-image   │
│  │   └── Responsive grid layout             │
│  └── Python backend (existing game logic)    │
│      ├── SQLite DB (unchanged)               │
│      ├── Event bus (unchanged)               │
│      ├── Rival AI (unchanged)                │
│      ├── Interpretation layer (unchanged)    │
│      └── JS↔Python bridge (pywebview API)   │
└─────────────────────────────────────────────┘
```

## What stays the same
- ALL Python game logic (src/services/, src/interpretation/, src/rival_ai/)
- SQLite database (schema, data, queries)
- Event bus architecture
- Game state management
- All planning docs (they describe WHAT to build, not HOW to render)

## What changes
- `src/ui/` replaced with HTML/CSS/JS + thin Python bridge
- CTk components → HTML/CSS components
- Theme system → CSS variables file
- Screen rendering → HTML templates + JS data binding

## Migration phases
1. Dashboard prototype (this task) — prove visual quality
2. App shell (top bar, sidebar, navigation)
3. Roster screen
4. Fighter Profile screen
5. Free Agents screen
6. Remaining 18 screens

## CSS Design System (from GUI_PLAN §4)

### Colors (CSS variables)
```css
:root {
  --bg-base: #0a0c10;
  --bg-surface: #15181f;
  --bg-card: #1c2028;
  --bg-card-elevated: #252a33;
  --border-subtle: #2a2f38;
  --border-strong: #3a4049;
  --text-primary: #e8eaed;
  --text-secondary: #aab0b8;
  --text-tertiary: #6b7280;
  --text-on-gold: #1a1410;
  --crimson: #d63a3f;
  --gold: #e0a957;
  --gold-bright: #f5c878;
  --gold-tint: rgba(224,169,87,0.10);
  --crimson-tint: rgba(214,58,63,0.10);
  --success: #4ade80;
  --warning: #fbbf24;
  --danger: #ef4444;
}
```

### Typography
```css
@font-face { font-family: 'Oswald'; src: url('assets/fonts/Oswald-Bold.ttf'); }
@font-face { font-family: 'Inter'; src: url('assets/fonts/Inter-Regular.ttf'); }
/* etc for all weights */

.display { font-family: 'Oswald', sans-serif; font-size: 36px; font-weight: 700; }
.display-small { font-family: 'Oswald', sans-serif; font-size: 24px; font-weight: 600; letter-spacing: 0.02em; }
.h1 { font-family: 'Inter', sans-serif; font-size: 22px; font-weight: 700; }
.h2 { font-family: 'Inter', sans-serif; font-size: 18px; font-weight: 700; }
.body { font-family: 'Inter', sans-serif; font-size: 14px; }
.body-small { font-family: 'Inter', sans-serif; font-size: 13px; }
.caption { font-family: 'Inter', sans-serif; font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
.descriptor { font-family: 'Inter', sans-serif; font-size: 14px; font-style: italic; }
.mono { font-family: 'JetBrains Mono', monospace; font-size: 14px; }
```

### Textures
```css
body {
  background-color: var(--bg-base);
  background-image: url('assets/textures/noise_grain.png');
  background-blend-mode: overlay;
}
```

### Key CSS advantages over CTk
- Real transparency (`opacity`, `rgba()`)
- Real gradients (`linear-gradient()`)
- Real background images (`background-image`)
- Real shadows (`box-shadow`)
- Real animations (`transition`, `@keyframes`)
- Web fonts (no registration issues)
- CSS Grid (proper 12-column layout)
- Flexbox (proper alignment)
