# Delivery — Akustik-Schale / Acoustic Bowl

## Summary

Desktop-first UI polish plus a new **Akustik-Schale** tab backed by a multilayer
1D transfer-matrix model of the titanium face / piezo / adhesive stack.

**Do not git push** from this tree — parent agent pushes.

## Physics / calibration

### Immutable manufacturer anchors
- ERA = 3.0 cm² → d_eq ≈ 19.54 mm
- I_max = 0.5 W/cm² SATA, P_ac_max = 1.5 W
- f0 ∈ {10, 19} MHz (home)
- Face: titanium (+ PVD on 19)
- Tissue c = 1540 m/s; gel Z ≈ 1.5 MRayl; air Z ≈ 400 Rayl

### Calibration-only (editable, UI badge)
File: `config/calibration_bowl.yaml` (`CALIBRATION_PRESET: true`)

| Parameter | Typical range | Notes |
|-----------|---------------|-------|
| Ti thickness | 0.1–1.0 mm | not published |
| Piezo thickness | ~λ/2 in ceramic | suggested from c_pzt/(2 f0), overridable |
| Piezo diameter | ≤ face diameter | |
| Glue thickness | 1–50 µm | thick glue → mismatch / loss |
| Material Z, c, ρ | literature | Ti / PZT / epoxy / cyano / gel / tissue |

Uncertain values are **never** presented as factory defaults.

### Bowl model (`src/acoustic_bowl.py`)
Stack: **PZT → glue → Ti → gel → tissue** (or air load).

Computes:
- Input impedance Z_in(f), intensity T(f)/R(f)
- Interface pressure/velocity
- Energy partition: radiated / glue loss / piezo heat / Ti loss
- Glue & Ti thickness sweeps (P_ac, η, resonance shift)
- Simple piston near-field intensity map
- Air load → T≈0, P_ac=0, heat in piezo/glue

Absolute radiated power is mapped onto the manufacturer P_ac budget with a
calibration electro-acoustic efficiency (≈0.65); relative glue/Ti trends are
physics-driven.

### Therapy sim consistency
- `src/acoustic_stack.py` keeps no-gel → P_ac≈0
- Half-value depth: I(x½)=I0/2 with α=ln2/(2 x½) — covered by anchors + bowl tests
- Two-scale integrator / duty flags unchanged; `tests/test_anchors.py` green

## API

| Method | Path | Role |
|--------|------|------|
| GET/POST | `/api/bowl/params` | get/set calibration geometry; POST returns full analyze |
| GET | `/api/bowl/spectrum` | T/R/Z around f0 |
| POST | `/api/bowl/sweep` | `{kind: glue\|titanium, n, h_min_m?, h_max_m?}` |
| GET | `/api/bowl/field` | near-field I(z,r) |
| GET | `/api/bowl/analyze` | full JSON for charts |

## UI

- Tab **Therapie** / **Akustik-Schale** (i18n DE+RU: `nav.therapy`, `nav.bowl`)
- Bowl: schematic SVG (dual µm/mm scale), spectrum, glue sweep, Ti sweep, energy doughnut, on-axis near-field
- Desktop: wider grid, sticky header, larger chart panes, dark/light theme

## Tests

```bash
pytest -q
```

Includes `tests/test_anchors.py` + `tests/test_acoustic_bowl.py`
(air load, glue sensitivity, Ti resonance shift, ERA/λ/2 helpers, half-value audit).

## How to open the new tab

1. `make run` or `python -m app.main` → http://127.0.0.1:8765
2. Click **Akustik-Schale** / **Акустическая чаша** in the top nav
3. Adjust Ti/glue/piezo (calibration badge), press **Analysieren**

## Limitations

- 1D normal-incidence transfer matrix — not full 3D diffraction / IEC hydrophone map
- Near-field map is a Fresnel piston educational view, not Rayleigh–Sommerfeld
- Ti/piezo/glue thicknesses are **model parameters**, not factory leaks
- Absolute electro-acoustic efficiency is calibrated, not measured on a bench
- Home devices remain mono-frequency; LDM stub unchanged

## Files touched (high level)

- `src/acoustic_bowl.py` (new), `config/calibration_bowl.yaml` (new)
- `src/acoustic_stack.py` (bridge helper)
- `app/main.py` (bowl routes)
- `app/templates/index.html`, `app/static/js/app.js`, `app/static/css/style.css`
- `locales/de.json`, `locales/ru.json`
- `tests/test_acoustic_bowl.py`, `README.md`, this file
