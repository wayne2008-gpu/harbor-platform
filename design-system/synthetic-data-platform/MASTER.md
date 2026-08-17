# Design System Master File

> **LOGIC:** When building a specific page, first check
> `design-system/synthetic-data-platform/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Synthetic Data Platform
**Generated:** 2026-08-17 12:04:17
**Category:** Analytics Dashboard
**Design Dials:** Variance 4/10 (Balanced / Modern) | Motion 3/10 (Subtle) | Density 9/10 (Dense / Dashboard)

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#1E40AF` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#3B82F6` | `--color-secondary` |
| On Secondary | `#000000` | `--color-on-secondary` |
| Accent/CTA | `#D97706` | `--color-accent` |
| On Accent/CTA | `#000000` | `--color-on-accent` |
| Background | `#F8FAFC` | `--color-background` |
| Foreground | `#1E3A8A` | `--color-foreground` |
| Card | `#FFFFFF` | `--color-card` |
| Card Foreground | `#1E3A8A` | `--color-card-foreground` |
| Muted | `#E9EEF6` | `--color-muted` |
| Muted Foreground | `#475569` | `--color-muted-foreground` |
| Border | `#DBEAFE` | `--color-border` |
| Destructive | `#DC2626` | `--color-destructive` |
| On Destructive | `#FFFFFF` | `--color-on-destructive` |
| Ring | `#1E40AF` | `--color-ring` |

**Color Notes:** Blue data + amber highlights [Accent adjusted from #F59E0B]

### Typography

- **Heading Font:** Inter / system sans
- **Body Font:** Inter / system sans
- **Monospace Font:** Fira Code / ui-monospace / SFMono-Regular
- **Mood:** dashboard, data, analytics, technical, precise

Keep the current application font stack for MVP implementation. Use monospace only
for IDs, COS URIs, JSON, checksums, artifact paths, and code-like values.

### Spacing Variables

*Density: 9/10 — Dense / Dashboard*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `2px` / `0.125rem` | Tight gaps |
| `--space-sm` | `4px` / `0.25rem` | Icon gaps, inline spacing |
| `--space-md` | `8px` / `0.5rem` | Standard padding |
| `--space-lg` | `12px` / `0.75rem` | Section padding |
| `--space-xl` | `16px` / `1rem` | Large gaps |
| `--space-2xl` | `24px` / `1.5rem` | Section margins |
| `--space-3xl` | `32px` / `2rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: #1E40AF;
  color: white;
  min-height: 36px;
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 600;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #1E40AF;
  border: 1px solid #1E40AF;
  min-height: 36px;
  padding: 8px 12px;
  border-radius: 8px;
  font-weight: 600;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
  cursor: pointer;
}
```

### Panels

```css
.panel {
  background: #FFFFFF;
  border: 1px solid #DBEAFE;
  border-radius: 8px;
  padding: 12px;
  box-shadow: var(--shadow-sm);
}

.panel + .panel {
  margin-top: 12px;
}
```

Use framed panels for repeated items, modals, and tool surfaces. Do not put cards
inside cards, and do not style page sections as decorative floating cards.

### Inputs

```css
.input {
  min-height: 36px;
  padding: 8px 10px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #1E40AF;
  outline: none;
  box-shadow: 0 0 0 3px #1E40AF20;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: var(--shadow-xl);
  max-width: 560px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Data-Dense Dashboard

**Keywords:** Multiple charts/widgets, data tables, KPI cards, minimal padding, grid layout, space-efficient, maximum data visibility

**Best For:** Business intelligence dashboards, financial analytics, enterprise reporting, operational dashboards, data warehousing

**Key Effects:** Hover tooltips, chart zoom on click, row highlighting on hover, smooth filter animations, data loading spinners

### Application Pattern

**Pattern Name:** Operational Workbench

- First screen is the working console, not a landing page or sales page.
- Primary navigation is `Workbench`, `Datasets`, `Tasks`, `Results`, `Settings`.
- Every list filter, pagination state, task builder prefill, and trajectory tab
  must be reflected in the URL.
- Harbor internals are diagnostics and provenance, not primary navigation.
- Dense tables are preferred on desktop. Mobile may switch to record cards or
  local table scrolling, but the page must not create horizontal scroll.

---

## Motion

Use subtle CSS transitions only for hover, focus, tab switches, loading feedback,
and filter state changes. Do not add GSAP or scroll reveal to the MVP frontend.
Respect `prefers-reduced-motion` and render the final state immediately when
motion is reduced.

---

## Anti-Patterns (Do NOT Use)

- Avoid: Ornate design
- Avoid: No filtering

### Additional Forbidden Patterns

- **Emojis as icons**: Use SVG icons (Heroicons, Lucide, Simple Icons)
- **Missing cursor:pointer**: All clickable elements must have cursor:pointer
- **Layout-shifting hovers**: Avoid scale transforms that shift layout
- **Low contrast text**: Maintain 4.5:1 minimum contrast ratio
- **Instant state changes**: Always use transitions (150-300ms)
- **Invisible focus states**: Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
