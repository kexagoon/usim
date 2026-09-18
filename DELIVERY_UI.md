# DELIVERY_UI — Professional desktop dashboard (2026-09-18)

## Goal
Desktop-first calm professional UI for the Skinova / Wellcomet simulator.
Functional behaviour and physics APIs unchanged; layout/CSS/structure only
(plus chart resize hooks). Build stamp: `ui-pro-2026-09-18`.

## Layout summary

### Global
- Sticky top toolbar: brand + calibration badge, Therapie | Akustik-Schale tabs,
  DE|RU, model select, Start/Pause/Reset, Dock/Undock/Write, Theme.
- Quiet disclaimer strip under toolbar.
- Dark / light themes with shared 8px spacing scale, rounded cards (8–10px),
  soft borders/shadows, accessible focus rings.

### Therapy tab (`#tab-therapy`)
- **2-column CSS grid** (≥1200px): left sidebar ~380px, right flex.
- **Left (sticky, scrollable accordion)**:
  Programm (open), Intensität (open), Piezo/Treiber, Akustik, Operator,
  Sicherheit 19, Batterie, Selftest, Export — advanced sections collapsed by
  default via `<details>`. Contraindications note at bottom.
- **Right**:
  - Live KPI strip: FSM, I_SATA, P_ac, T_piezo, T_skin, SoC, Kontakt, Rest.
  - Chart grid 2×N; each plot in a card with title + caption; chart area
    fixed height 280px (300px ultrawide).
- Selftest results as compact badge list (pass/fail).

### Bowl tab (`#tab-bowl`)
- Same 2-column pattern.
- **Left**: frequency chips (clear active state), preset chip row, accordion
  (Drive open, Geometry open with primary Titan-Ø `bowlTiD`, Materials /
  Electrode / Matching / A-B collapsed). Analyze / Defaults at bottom.
- **Right**: KPI metrics strip → large centered schematic (`#bowlSvg`) →
  chart grid (spectrum, sweeps, energy, field, profile, phase) each in a
  titled card with caption.

### Mobile (<1200px)
- Columns stack; sidebars become static full-width; charts collapse to
  single column under ~800px. Toolbar wraps without horizontal page scroll.

## Charts / JS
- Chart.js: `responsive: true`, `maintainAspectRatio: false`.
- Containers have explicit height so plots do not collapse.
- `resizeAllCharts()` on tab switch, window resize (debounced), and theme toggle.

## IDs
- **No ID renames.** All existing element IDs used by `app.js` preserved
  (including `bowlTiD` editable / not readonly, all canvas IDs, buttons).

## Files touched
- `app/templates/index.html` — structure rewrite (IDs preserved)
- `app/static/css/style.css` — full design system rewrite
- `app/static/js/app.js` — resize hooks only
- `Dockerfile` — `USIM_BUILD=ui-pro-2026-09-18`
- `app/main.py` — `/api/build` note / default stamp
- `DELIVERY_UI.md` — this file

## Verify
```bash
pytest -q
# TestClient GET / → 200; HTML contains bowlTiD without readonly
```
