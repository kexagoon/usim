# Delivery notes — Skinova / Wellcomet Simulator

## Run

```bash
cd /workspace/skinova-wellcomet-simulator
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m app.main
```

- UI: http://127.0.0.1:8765  
- Alternatives: `make run`, `make test`, `uvicorn app.main:app --host 127.0.0.1 --port 8765`

## Which YAML controls programs

**`config/programs.yaml`** — all program names, modes, durations, I_SATA, PRF, zones.  
Flag `CALIBRATION_PRESET: true` marks I_set/mode/T as **calibration**, not factory firmware.

Also:

- `config/devices.yaml` — hardware constants, piezo/driver/battery/safety defaults  
- `config/tissue.yaml` — tissue stack + acoustic stack materials  

## Key modules

| Path | Role |
|------|------|
| `src/simulation.py` | Two-scale orchestrator |
| `src/piezo_bvd.py` | BVD electrical model |
| `src/driver.py` | HF driver + duty / I_SATA limits |
| `src/acoustic_stack.py` | T-matrix stack; no gel → P_ac≈0 |
| `src/propagation.py` | Depth intensity, x½, near field |
| `src/bioheat.py` | Pennes 1D + piezo RC thermal |
| `src/fsm_sonotrode.py` | Handpiece FSM + NVM |
| `src/station.py` | Program write + charge |
| `src/operator_motion.py` | Operator paths |
| `src/i18n.py` | DE/RU locales |
| `src/ldm_triple.py` | **Separate** clinical LDM stub (disabled for home) |
| `app/main.py` | FastAPI + SPA |
| `tests/test_anchors.py` | 7 validation anchors |

## Stack

Python 3.11+, FastAPI + Jinja2 + static JS (Chart.js). One stack only.

## Known limitations

- Behavioural model, not reverse-engineered firmware or IEC hydrophone maps.
- PRF / exact “1:2” meaning / battery Wh / NTC thresholds are calibration defaults.
- Home devices: monofrequency + burst only; LDM multi-MHz hopping is stubbed separately.
- Macro timestep (1–10 ms) approximates burst heating; carrier cycles are not integrated at 19 MHz for full sessions.
- Without gel, integrated `step()` pauses on no-contact (Skinova 19 behaviour); air-heating is validated via driver+thermal path in tests.
- No medical cure claims; contraindications are hint text only.

## Git

Do **not** init/push from this tree unless the parent agent does — intended remote: https://github.com/kexagoon/usim

## Port note

Default bind is `127.0.0.1:8765` (`app.main:main`). If that port is occupied, use:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 18765
```


See also: DELIVERY_CUP_HELP.md (half-cup geometry + UI help/hints pass).
