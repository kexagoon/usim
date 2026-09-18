# DELIVERY_UI — Professional desktop dashboard (2026-09-18)

## Goal
Desktop-first calm professional UI for the Skinova / Wellcomet simulator.
Build stamp: `ui-collapse-power-2026-09-18`.

## Layout summary

### Global
- Sticky top toolbar: brand + calibration badge, Therapie | Akustik-Schale tabs,
  DE|RU, model select, Start/Pause/Reset, Dock/Undock/Write, **Einstellungen
  ausblenden/einblenden**, Theme.
- Quiet disclaimer strip under toolbar.
- Dark / light themes with shared 8px spacing scale, rounded cards (8–10px),
  soft borders/shadows, accessible focus rings.

### Collapsible settings (`usim.settingsCollapsed`)
- Therapy and Bowl: left `.settings-col` toggles via toolbar button
  `#btnSettingsCollapse` and local «« controls in each sidebar head.
- Preference persisted in `localStorage` key `usim.settingsCollapsed`.
- When collapsed: sidebar width 0 / hidden; `.results-col` uses full width;
  slim vertical reopen tab (`#btnSettingsReopenTherapy` /
  `#btnSettingsReopenBowl`) on the left edge.
- After toggle: `resizeAllCharts()` (+ rAF) so Chart.js refits.

### Board / source power («Platine / Quelle»)
- Therapy accordion `#secBoardSource`: `pcb_drive_v`, `vdrive_peak`, power
  presets 25/50/75/100%, `drive_level` slider, `eta_elec`, `p_elec_max_w`,
  `i_sense_window_ms` (Kalibrierung). Help: electronics feed one lead to piezo;
  return via titanium.
- Bowl: `#secBowlBoardSource` with `bowlPcbV`, presets (wire to `bowlDrive`),
  `bowlPElecMax`; existing drive slider kept.
- Wired to `/api/settings` and `/api/bowl/params`. Physics: `drive_level` scales
  I_set / bowl drive; `pcb_drive_v` sets board peak (bowl ∝ V²); `p_elec_max_w`
  clamps P_bat / drive budget.

### Therapy tab (`#tab-therapy`)
- **2-column CSS grid** (≥1200px): left sidebar ~380px, right flex.
- **Left (sticky, scrollable accordion)**: Programm, Intensität, Piezo/Treiber,
  **Platine / Quelle**, Akustik, Operator, Sicherheit 19, Batterie, Selftest,
  Export.
- **Right**: Live KPI strip + chart grid.

### Bowl tab (`#tab-bowl`)
- Same 2-column pattern with collapse support.
- **Left**: frequency chips, presets, Drive / Geometry / Materials /
  **Platine / Quelle** / Matching / A-B.
- **Right**: KPIs → schematic → charts.

### Mobile (<1200px)
- Columns stack; reopen control becomes a horizontal chip.

## Charts / JS
- Chart.js: `responsive: true`, `maintainAspectRatio: false`.
- `resizeAllCharts()` on tab switch, window resize (debounced), theme toggle,
  **and settings collapse**.

## IDs
- **No ID renames.** Existing IDs preserved (`bowlTiD` editable, all canvases,
  `vdrive`, `etaElec`, `bowlPcbV`, `bowlDrive`, …). New IDs only for collapse /
  board controls.

## Files touched
- `app/templates/index.html`, `app/static/css/style.css`, `app/static/js/app.js`
- `app/main.py`, `src/driver.py`, `src/simulation.py`, `src/acoustic_bowl.py`
- `locales/de.json`, `locales/ru.json`, `config/calibration_bowl.yaml`
- `tests/test_ui_collapse_power.py`
- `Dockerfile` — `USIM_BUILD=ui-collapse-power-2026-09-18`
- `DELIVERY_UI.md` — this file

## Verify
```bash
pytest -q
# TestClient GET / → 200; HTML has btnSettingsCollapse; bowlTiD not readonly
```
