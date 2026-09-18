# Delivery: Akustik-Schale time-dependent thermal–acoustic transient

**Build:** `USIM_BUILD=bowl-transient-2026-09-18`  
**Date:** 2026-09-18  
**Scope:** Bowl tab only. No git push.

## Analysieren behaviour (unchanged contract)

`Analysieren` still **POSTs all current form params** to `/api/bowl/params` (geometry, materials, drive, board, **and** thermal/transient fields), then refreshes spectrum / sweeps / profile / field.  
Additionally it POSTs `/api/bowl/transient` with `{duration_s, dt_s, …thermal}` and updates time charts + KPI strip.  
**All settings apply on Analysieren** — nothing auto-runs on every slider tick.

## What the transient couples

Each macro step (`dt` ≈ 0.05–0.5 s, adaptive by duration, max 12 min):

1. **Acoustics** → energy partition at f0 (`P_ac`, glue/piezo/Ti losses, η)  
2. **Heat** into lumped nodes `T_piezo`, `T_glue`, `T_ti` (+ optional load)  
3. **Cooling** via node conduction + convection to `T_amb`  
4. **Property feedback:** glue α ↑ with `T_glue`, stack η / kt ↓ with `T_piezo`, optional resonance-shift tracker  
5. **Drive derate** between `T_warn` → `T_off` (smooth cos or hard)  
6. Loop → next step  

Clearly labeled **CALIBRATION_PRESET** — not factory firmware.

## Files

| Path | Role |
|------|------|
| `src/bowl_transient.py` | Lumped RC + coupling + series/summary |
| `config/calibration_bowl.yaml` | `thermal` + `ranges_thermal` |
| `app/main.py` | `POST/GET /api/bowl/transient`, thermal on params, build stamp |
| `app/templates/index.html` | Zeitverlauf controls + 4 charts + KPI |
| `app/static/js/app.js` | Collect/post/render on Analysieren |
| `locales/de.json`, `locales/ru.json` | Full DE+RU strings |
| `tests/test_bowl_transient.py` | Heating, air vs gel, duration, derate, API |

## UI controls added

- Duration presets: 10 s / 30 s / 1 min / 2 min / 5 min / custom (≤ 720 s)  
- `dt`, `T_amb`, advanced: `T_warn`, `T_off`, `h_conv`, `k_*`, `G_*`, smooth derate  
- Charts (~280–300 px): temperatures; P_ac+η; drive/derate; losses+glue_factor  
- KPI: ΔT_piezo, P_ac start→end, max T_glue, derate min  
- `bowlTiD` remains editable; collapse panel IDs preserved  

## API

- `POST /api/bowl/transient` `{ duration_s, dt_s? , thermal… }` → series + summary  
- `GET /api/bowl/transient` → last-run cache  
- `/api/bowl/params` help includes `thermal` ranges; POST accepts thermal keys  

## Tests

`pytest` — transient suite + existing green. See report in agent final message.
