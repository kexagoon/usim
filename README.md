# Skinova / Wellcomet Ultraschall-Simulator

**RU (кратко):** Физический симулятор домашних аппаратов Wellcomet Skinova (10/19 МГц и MED). Не является медицинским изделием и не даёт лечебных обещаний. Калибровочные пресеты программ (`CALIBRATION_PRESET` в `config/programs.yaml`) — **не** заводская прошивка. Запуск: `make run` или `python -m app.main` → http://127.0.0.1:8765 . Язык UI по умолчанию DE, переключение RU без потери состояния.

---

## Übersicht

Verhaltens- und Physiksimulation der Wellcomet **Skinova**-Heimgeräte:

| Modell | Frequenz | Programme |
|--------|----------|-----------|
| SKINOVA_10 | 10 MHz | 6 kosmetische |
| SKINOVA_19 | 19 MHz | 10 kosmetische + NTC/IMU |
| SKINOVA_MED | 10 MHz | kosmetisch + medizinische Slots |

**Kein** LDM-Triple-Frequenzhopping in den Heimmodellen (optionaler Stub: `src/ldm_triple.py`).

Kalibrierwerte (I_set, T_warn/T_off, BAT_CAPACITY, …) sind **Modellparameter**, nicht geleakte Werkswerte. In der UI: Badge *„Kalibrierung, nicht Werkspreset“*.

## Installation

```bash
cd skinova-wellcomet-simulator
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Voraussetzungen: Python **3.11+**.

## Start

```bash
make run
# oder:
python -m app.main
# oder:
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Browser: **http://127.0.0.1:8765**

## Tests

```bash
make test
# oder:
pytest -q
```

Sieben Validierungsanker (SPEC Teil N) in `tests/test_anchors.py`.

## Konfiguration (YAML)

| Datei | Inhalt |
|-------|--------|
| **`config/programs.yaml`** | Programme, I_SATA/Mode/Dauer/PRF — gesteuert über `CALIBRATION_PRESET` |
| `config/devices.yaml` | Station/Sonotrode, Piezo, Treiber, Safety-Defaults |
| `config/tissue.yaml` | Gewebeschichten, α, Bioheat |

Programme ändern → **`config/programs.yaml`** bearbeiten.

## Physik-Module (`src/`)

- `piezo_bvd.py` — Butterworth–Van Dyke (C0,L1,C1,R1), Luft vs. Gel
- `driver.py` — Vdrive, η_elec, Regelung auf I_SATA, Duty-Interpretation
- `acoustic_stack.py` — T-Matrix PZT→Kleber→Ti→Gel→Haut; ohne Gel P_ac≈0
- `propagation.py` — I(x)=I0·exp(−2αx), α=ln2/(2·x½), Near-Field
- `bioheat.py` — 1D Pennes + Dosis; Piezo-RC-Wärme
- `fsm_sonotrode.py` — Zustände + NVM
- `station.py` — `write(ProgramBlob)`, `charge()`
- `operator_motion.py` — Kreis/Linear/Still, Kraft→Geldicke
- `simulation.py` — Zweiskalen-Integrator
- `i18n.py` — DE Standard, RU zweite Sprache (localStorage)

Herstellerlimits (unveränderlich in der Logik): I_max=0,5 W/cm² SATA, P_ac_max=1,5 W, T_prog≤12 min, f0∈{10,19} MHz.

## i18n / UI

- Standard: **Deutsch**; Umschalten **DE|RU** ohne Reload-Verlust (localStorage)
- Alle UI-Strings in `locales/de.json` / `locales/ru.json`
- Dark/Light-Theme, viele Einstellungen, Plots (Chart.js), CSV/PNG-Export, Selbsttest

## Hinweise / Disclaimer

- Keine Heilversprechen; Kontraindikationen nur als Hinweistext.
- Simulator ≠ Zertifizierung / IEC-Messung der echten Sonotrode.
- MIT-Lizenz — siehe `LICENSE`.

## Spezifikation

Hintergrund (RU): `SPEC_RU.txt`. Liefernotiz: `DELIVERY.md`.


## Online-Deploy (permanente URL)

GitHub speichert nur den Code. Für eine permanente Web-URL (Handy/PC überall):

1. Bei [Render](https://render.com) anmelden (kostenloser Plan).
2. **New → Blueprint** und dieses Repository verbinden (`kexagoon/usim`).
3. `render.yaml` erzeugt den Web-Service automatisch.
4. Nach dem Deploy: URL wie `https://skinova-wellcomet-simulator.onrender.com`.

Hinweis: Der Free-Plan schläft nach Idle ein; der erste Aufruf kann 30–60 s dauern.

Docker lokal:

```bash
docker build -t skinova-sim .
docker run --rm -p 8765:8765 skinova-sim
```

