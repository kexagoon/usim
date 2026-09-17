# Delivery — Frequencies {1,3,10,19} MHz + richer acoustic bowl

**Do not git push** — parent agent pushes and deploys.

## Frequency policy

| Role | Frequencies |
|------|-------------|
| Allowed simulation set | **1 / 3 / 10 / 19 MHz** everywhere `f0` is user-settable |
| Home manufacturer defaults | SKINOVA_10 / MED → **10 MHz**, SKINOVA_19 → **19 MHz** |
| LDM_TRIPLE (stub) | 1 / 3 / 10 (+ optional 19) — clinical, not home firmware |

UI shows all four frequencies. Hint (DE/RU): 1/3 MHz are clinical/LDM-class **simulation** options — not claiming factory home firmware hops.

Shared module: `src/frequencies.py` (`ALLOWED_F0_HZ`, λ, λ/2 piezo thickness, x½).

### Half-value depths x½

| f0 | x½ | Source |
|----|-----|--------|
| 10 MHz | 3.0 mm | manufacturer-ish claim |
| 19 MHz | 1.5 mm | manufacturer-ish claim |
| 1 MHz | ~30 mm | **calibration** (α∝f from 10 MHz) |
| 3 MHz | ~10 mm | **calibration** (α∝f from 10 MHz) |

Editable via `config/devices.yaml` → `half_value_depth_m`. Badge: calibration-only.

Therapy sim: `POST /api/settings` with `f0_hz` rebuilds piezo/propagation/stack for that frequency.

## Richer acoustic bowl

### Materials / presets
- Piezo: PZT-4, PZT-5A, PZT-8, BaTiO3, custom (ρ/c/Z/kt)
- Glue: epoxy, cyanoacrylate, silicone soft, thick bond, custom
- Face: titanium, titanium+PVD, stainless (what-if), custom
- Load: air, water, gel, soft tissue, fat, bone, gel+tissue
- Optional matching layer (Ti→gel); backing air vs heavy (bandwidth trade-off)

### Geometry
Ti thickness/diameter, piezo thickness (auto λ/2 + override), piezo diameter, glue/gel thickness, matching on/off + thickness.

### Analyses / API
| Endpoint | Role |
|----------|------|
| GET/POST `/api/bowl/params` | geometry + materials |
| POST `/api/bowl/preset` | named calib presets |
| GET `/api/bowl/spectrum` | \|T\|, \|R\|, \|Z\|, **phase** (selectable span) |
| POST `/api/bowl/sweep` | glue \| titanium \| **piezo_diameter** \| **f0** |
| GET `/api/bowl/field` | near-field Fresnel map |
| GET `/api/bowl/profile` | 1D \|p\|(z) + TOF |
| GET `/api/bowl/analyze` | full metrics + energy partition |
| POST `/api/bowl/compare` | A/B preset JSON deltas |
| GET `/api/frequencies` | policy dictionary |

UI: frequency chips, collapsible sections, preset buttons, larger charts, A/B compare panel. DE+RU i18n + calibration badge.

## Tests

```bash
pytest -q
```

Anchors: home defaults still 10/19; allowed set {1,3,10,19}; explicit 1/3 override OK. Bowl: λ/2 at all f0, air→P_ac≈0 at 1/3 MHz, I_SATA≤0.5, P_ac≤1.5.

## Files touched

- `src/frequencies.py` (new), `src/acoustic_bowl.py`, `src/simulation.py`, `src/propagation.py`, `src/ldm_triple.py`
- `config/devices.yaml`, `config/calibration_bowl.yaml`, `config/programs.yaml` (LDM_TRIPLE stubs)
- `app/main.py`, `app/templates/index.html`, `app/static/js/app.js`, `app/static/css/style.css`
- `locales/de.json`, `locales/ru.json`
- `tests/test_anchors.py`, `tests/test_acoustic_bowl.py`
- `DELIVERY_FREQ.md`, `DELIVERY_BOWL.md` (pointer)
