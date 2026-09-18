# Delivery — Cup geometry + UI help pass

**Do not git push** — parent agent pushes/deploys.

## Geometry (critical)

Titanium is a **half-cup / bowl (полустакан)**:

- Piezo glued on the **inside bottom** of the cup
- Cup screwed to the handpiece (PCB inside)
- Wiring: PCB → piezo electrode; return via **Ti cup walls**
- Acoustic exit: **outer Ti face** (down toward gel/tissue)
- Optional educational **droplet/mist** cue on outer face (not a medical claim)

1D T-matrix stack along radiating axis: **piezo → glue → Ti bottom → [match] → load**.  
Side walls are electrical return only.

New calibration params in `config/calibration_bowl.yaml` / UI:  
`cup_inner_diameter_m`, `cup_outer_diameter_m`, `cup_wall_thickness_m`, `cup_depth_m`,  
`pcb_drive_v`, `r_wire_piezo_ohm`, `r_ti_return_ohm`, `droplet_demo`.  
ERA d_eq ≈ 19.54 mm still consistent with defaults. Unpublished depths stay CALIBRATION_PRESET.

## UI documentation

- DE + RU `hints.*` / `bowl.help_*` / `captions.*` / `bowl.caption_*` for therapy + bowl controls and charts
- `?` info affordances + help paragraphs under dense controls
- Chart captions under therapy and bowl plots
- SVG schematic: PCB, screws, two wires, half-cup cross-section, downward US arrows, optional mist

## Editable extras (therapy)

BVD: C0, k_eff², Q_air, Q_gel (C1/L1 derived live); Vdrive, η_elec, stack η; α-law n; all prior safety/motion/battery/f0/I_SATA fields remain POST-bound.

## Tests

`pytest -q` — stack order, air radiates ~0, cup geometry from YAML, electrode R effect.

## Editable Titan-Durchmesser / ERA link (2026-09-18)

**Was locked:** `#bowlTiD` had HTML `readonly` and JS/`bowl_params_from_dict` always overwrote `ti_diameter_m` from cup outer / ERA default (~19.54 mm).

**Fix:**
- `#bowlTiD` is editable (primary geometry control).
- Changing Titan-Ø sets `ti_diameter_m` + `cup_outer_diameter_m` and updates `#bowlEra` via π(d/2)².
- Changing ERA updates equivalent diameter (and outer Ø).
- Changing cup outer Ø also updates Titan-Ø / ERA.
- Piezo Ø clamps to ≤ min(inner cup, radiating Ø) with on-screen hint.
- Help DE+RU: manufacturer ERA≈3 cm² is default only, not a lock.
- `POST /api/bowl/params` keeps custom `ti_diameter_m` (e.g. 0.016).
