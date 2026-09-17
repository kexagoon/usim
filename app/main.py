"""FastAPI entrypoint: serves SPA + JSON API for the Skinova simulator."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.i18n import all_strings, list_langs
from src.simulation import Simulation, SimulationConfig
from src.acoustic_bowl import (
    AcousticBowl,
    apply_named_preset,
    bowl_params_from_dict,
    compare_bowl_presets,
    default_bowl_params,
    params_help,
)
from src.frequencies import ALLOWED_F0_HZ, frequency_policy_dict, validate_f0

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Skinova / Wellcomet Simulator", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# Global sim instance (single-user desktop tool)
_sim: Simulation | None = None


def get_sim() -> Simulation:
    global _sim
    if _sim is None:
        _sim = Simulation(SimulationConfig(model="SKINOVA_19", seed=42))
        _sim.load_program(1)
    return _sim


class SettingsIn(BaseModel):
    model: str | None = None
    program_id: int | None = None
    gel_present: bool | None = None
    path: str | None = None
    force_n: float | None = None
    i_set: float | None = None
    duration_s: float | None = None
    mode: str | None = None
    prf_hz: float | None = None
    duty_interpretation: str | None = None
    limit_domain: str | None = None
    t_warn_c: float | None = None
    t_off_c: float | None = None
    motion_still_s: float | None = None
    motion_eps: float | None = None
    bat_capacity_wh: float | None = None
    stack_efficiency: float | None = None
    vdrive_peak_v: float | None = None
    eta_elec: float | None = None
    c0_nF: float | None = None
    dt_macro_s: float | None = None
    seed: int | None = None
    enable_2d: bool | None = None
    f0_hz: float | None = None  # allowed {1,3,10,19}e6


class RunIn(BaseModel):
    seconds: float = Field(1.0, ge=0.01, le=720.0)
    dt_s: float | None = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, lang: str = Query("de")) -> HTMLResponse:
    lang = lang if lang in ("de", "ru") else "de"
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "lang": lang,
            "i18n": all_strings(lang),
            "langs": list_langs(),
        },
    )


@app.get("/api/i18n/{lang}")
async def api_i18n(lang: str) -> dict[str, Any]:
    return all_strings(lang if lang in ("de", "ru") else "de")


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    sim = get_sim()
    return sim.status_dict()


@app.get("/api/programs")
async def api_programs(model: str | None = None) -> dict[str, Any]:
    sim = get_sim()
    if model and model != sim.cfg.model:
        # peek without destroying state too hard
        tmp = Simulation(SimulationConfig(model=model, seed=sim.cfg.seed))
        return {"model": model, "programs": tmp.list_programs(), "calibration": True}
    return {
        "model": sim.cfg.model,
        "programs": sim.list_programs(),
        "calibration": bool(sim.programs.get("CALIBRATION_PRESET", True)),
    }


@app.post("/api/settings")
async def api_settings(body: SettingsIn) -> dict[str, Any]:
    global _sim
    sim = get_sim()
    cfg = sim.cfg
    rebuild = False

    if body.model is not None and body.model != cfg.model:
        cfg.model = body.model
        rebuild = True
    if body.seed is not None:
        cfg.seed = body.seed
        rebuild = True
    if body.duty_interpretation is not None:
        cfg.duty_interpretation = body.duty_interpretation
    if body.limit_domain is not None:
        cfg.limit_domain = body.limit_domain
        sim.driver.params.limit_domain = body.limit_domain
    if body.t_warn_c is not None:
        cfg.t_warn_c = body.t_warn_c
        sim.fsm.t_warn_c = body.t_warn_c
    if body.t_off_c is not None:
        cfg.t_off_c = body.t_off_c
        sim.fsm.t_off_c = body.t_off_c
    if body.motion_still_s is not None:
        cfg.motion_still_s = body.motion_still_s
        sim.fsm.motion_still_s = body.motion_still_s
    if body.motion_eps is not None:
        cfg.motion_eps = body.motion_eps
        sim.fsm.motion_eps = body.motion_eps
    if body.bat_capacity_wh is not None:
        cfg.bat_capacity_wh = body.bat_capacity_wh
        sim.bat_capacity_wh = body.bat_capacity_wh
    if body.stack_efficiency is not None:
        cfg.stack_efficiency = body.stack_efficiency
        sim.stack.stack_efficiency = body.stack_efficiency
        sim.driver.params.stack_efficiency = body.stack_efficiency
    if body.vdrive_peak_v is not None:
        cfg.vdrive_peak_v = body.vdrive_peak_v
        sim.driver.params.vdrive_peak_v = body.vdrive_peak_v
    if body.eta_elec is not None:
        cfg.eta_elec = body.eta_elec
        sim.driver.params.eta_elec = body.eta_elec
    if body.c0_nF is not None:
        cfg.c0_nF = body.c0_nF
        rebuild = True
    if body.dt_macro_s is not None:
        cfg.dt_macro_s = body.dt_macro_s
    if body.enable_2d is not None:
        cfg.enable_2d = body.enable_2d
    if body.i_set is not None:
        cfg.i_set_override = min(body.i_set, 0.5)
    if body.duration_s is not None:
        cfg.duration_override_s = min(body.duration_s, 720.0)
    if body.mode is not None:
        cfg.mode_override = body.mode
    if body.prf_hz is not None:
        cfg.prf_hz = body.prf_hz
    if body.force_n is not None:
        cfg.force_n = body.force_n
        sim.motion.force_n = body.force_n
    if body.path is not None:
        sim.set_path(body.path)
    if body.gel_present is not None:
        sim.set_gel(body.gel_present)
    if body.f0_hz is not None:
        cfg.f0_hz_override = validate_f0(float(body.f0_hz))
        rebuild = True

    if rebuild:
        pid = body.program_id or (sim.fsm.nvm.program_id or 1)
        _sim = Simulation(cfg)
        _sim.load_program(pid)
        sim = _sim
    elif body.program_id is not None:
        sim.load_program(body.program_id)
    elif any(
        x is not None
        for x in (body.i_set, body.duration_s, body.mode, body.prf_hz)
    ) and sim.fsm.nvm.program_id is not None:
        # re-write current program with overrides
        sim.load_program(sim.fsm.nvm.program_id)

    return sim.status_dict()


@app.post("/api/start")
async def api_start() -> dict[str, Any]:
    sim = get_sim()
    ok = sim.start()
    return {"ok": ok, **sim.status_dict()}


@app.post("/api/pause")
async def api_pause() -> dict[str, Any]:
    sim = get_sim()
    sim.pause()
    return sim.status_dict()


@app.post("/api/reset")
async def api_reset() -> dict[str, Any]:
    sim = get_sim()
    sim.reset()
    return sim.status_dict()


@app.post("/api/dock")
async def api_dock() -> dict[str, Any]:
    sim = get_sim()
    sim.fsm.dock()
    return sim.status_dict()


@app.post("/api/undock")
async def api_undock() -> dict[str, Any]:
    sim = get_sim()
    sim.fsm.undock()
    return sim.status_dict()


@app.post("/api/step")
async def api_step() -> dict[str, Any]:
    sim = get_sim()
    snap = sim.step()
    return {"snapshot": snap.__dict__, **sim.status_dict()}


@app.post("/api/run")
async def api_run(body: RunIn) -> dict[str, Any]:
    sim = get_sim()
    snaps = sim.run_for(body.seconds, body.dt_s)
    return {
        "n_steps": len(snaps),
        "last": snaps[-1].__dict__ if snaps else None,
        **sim.status_dict(),
    }


@app.get("/api/selftest")
async def api_selftest() -> dict[str, Any]:
    """Run the 7 validation anchors and return red/green results."""
    from tests.test_anchors import run_all_anchors

    results = run_all_anchors()
    return {"results": results, "all_pass": all(r["pass"] for r in results)}


@app.get("/api/export/csv")
async def api_export_csv() -> StreamingResponse:
    sim = get_sim()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "t_s",
            "state",
            "i_sata",
            "p_ac",
            "p_bat",
            "t_piezo_c",
            "t_skin_c",
            "soc",
            "contact",
            "t_remaining_s",
        ]
    )
    for s in sim.history:
        w.writerow(
            [
                s.t_s,
                s.state,
                s.i_sata,
                s.p_ac,
                s.p_bat,
                s.t_piezo_c,
                s.t_skin_surface_c,
                s.soc,
                int(s.contact),
                s.t_remaining_s,
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=skinova_sim.csv"},
    )


@app.post("/api/preset")
async def api_preset_save(request: Request) -> JSONResponse:
    data = await request.json()
    return JSONResponse({"ok": True, "preset": data})



# ---------------------------------------------------------------------------
# Acoustic bowl (Akustik-Schale) API — calibration geometry, not factory data
# ---------------------------------------------------------------------------

_bowl_params = default_bowl_params()


class BowlParamsIn(BaseModel):
    f0_hz: float | None = None
    drive_level: float | None = None
    load: str | None = None
    piezo_material: str | None = None
    glue_material: str | None = None
    face_material: str | None = None
    ti_thickness_m: float | None = None
    ti_diameter_m: float | None = None
    piezo_thickness_m: float | None = None
    piezo_diameter_m: float | None = None
    glue_thickness_m: float | None = None
    gel_thickness_m: float | None = None
    matching_enabled: bool | None = None
    matching_material: str | None = None
    matching_thickness_m: float | None = None
    backing: str | None = None
    era_cm2: float | None = None
    stack_efficiency: float | None = None
    kt: float | None = None
    spectrum_span: float | None = None
    piezo_rho: float | None = None
    piezo_c: float | None = None
    piezo_z_mrayl: float | None = None
    face_z_mrayl: float | None = None
    load_z_mrayl: float | None = None


def _get_bowl() -> AcousticBowl:
    return AcousticBowl(_bowl_params)


@app.get("/api/bowl/params")
async def api_bowl_params_get() -> dict[str, Any]:
    bowl = _get_bowl()
    return {
        "params": bowl.to_api_dict()["params"],
        "help": params_help(),
        "calibration": True,
        "result": bowl.to_api_dict(),
    }


@app.post("/api/bowl/params")
async def api_bowl_params_post(body: BowlParamsIn) -> dict[str, Any]:
    global _bowl_params
    data = body.model_dump(exclude_none=True)
    _bowl_params = bowl_params_from_dict(data, _bowl_params)
    bowl = _get_bowl()
    return {
        "params": bowl.to_api_dict()["params"],
        "help": params_help(),
        "calibration": True,
        "result": bowl.to_api_dict(),
    }


@app.get("/api/bowl/spectrum")
async def api_bowl_spectrum(
    n: int = Query(201, ge=21, le=1001),
    span: float = Query(0.15, ge=0.02, le=0.5),
) -> dict[str, Any]:
    bowl = _get_bowl()
    f0 = bowl.params.f0_hz
    bowl.params.spectrum_span = span
    spec = bowl.spectrum(f0 * (1 - span), f0 * (1 + span), n=n)
    return {
        "calibration": True,
        "f0_hz": f0,
        "span": span,
        "resonance_hz": bowl.find_resonance(spec),
        "f_hz": [p.f_hz for p in spec],
        "t_intensity": [p.t_intensity for p in spec],
        "r_intensity": [p.r_intensity for p in spec],
        "z_in_mag": [p.z_in_mag for p in spec],
        "z_in_real": [p.z_in_real for p in spec],
        "z_in_imag": [p.z_in_imag for p in spec],
        "z_in_phase_rad": [p.z_in_phase_rad for p in spec],
        "t_phase_rad": [p.t_phase_rad for p in spec],
    }


class BowlSweepIn(BaseModel):
    kind: str = "glue"  # glue | titanium | piezo_diameter | f0
    n: int = Field(40, ge=5, le=200)
    h_min_m: float | None = None
    h_max_m: float | None = None


@app.post("/api/bowl/sweep")
async def api_bowl_sweep(body: BowlSweepIn) -> dict[str, Any]:
    bowl = _get_bowl()
    kind = body.kind.lower()
    if kind in ("glue", "kleber", "adhesive"):
        h_min = body.h_min_m if body.h_min_m is not None else 1e-6
        h_max = body.h_max_m if body.h_max_m is not None else 50e-6
        data = bowl.sweep_glue(h_min, h_max, n=body.n)
        data["kind"] = "glue"
    elif kind in ("piezo_diameter", "piezo_d", "diameter"):
        d_min = body.h_min_m if body.h_min_m is not None else 0.010
        d_max = body.h_max_m if body.h_max_m is not None else None
        data = bowl.sweep_piezo_diameter(d_min, d_max, n=body.n)
        data["kind"] = "piezo_diameter"
    elif kind in ("f0", "frequency", "freq"):
        data = bowl.compare_frequencies()
        data["kind"] = "f0"
    else:
        h_min = body.h_min_m if body.h_min_m is not None else 1e-4
        h_max = body.h_max_m if body.h_max_m is not None else 1e-3
        data = bowl.sweep_titanium(h_min, h_max, n=body.n)
        data["kind"] = "titanium"
    data["calibration"] = True
    data["f0_hz"] = bowl.params.f0_hz
    return data


@app.get("/api/bowl/field")
async def api_bowl_field(
    nx: int = Query(50, ge=10, le=120),
    nr: int = Query(40, ge=10, le=100),
) -> dict[str, Any]:
    bowl = _get_bowl()
    field = bowl.near_field_map(nx=nx, nr=nr)
    field["calibration"] = True
    field["energy"] = bowl.to_api_dict()["energy"]
    return field


@app.get("/api/bowl/analyze")
async def api_bowl_analyze() -> dict[str, Any]:
    return _get_bowl().to_api_dict()


@app.get("/api/bowl/profile")
async def api_bowl_profile(n_per_layer: int = Query(20, ge=4, le=80)) -> dict[str, Any]:
    bowl = _get_bowl()
    data = bowl.depth_profile(n_per_layer=n_per_layer)
    data["calibration"] = True
    data["time_of_flight"] = bowl.time_of_flight()
    return data


@app.get("/api/frequencies")
async def api_frequencies() -> dict[str, Any]:
    return frequency_policy_dict()


class BowlPresetIn(BaseModel):
    name: str


@app.post("/api/bowl/preset")
async def api_bowl_preset(body: BowlPresetIn) -> dict[str, Any]:
    global _bowl_params
    _bowl_params = apply_named_preset(body.name, _bowl_params)
    bowl = _get_bowl()
    return {
        "params": bowl.to_api_dict()["params"],
        "help": params_help(),
        "calibration": True,
        "result": bowl.to_api_dict(),
        "preset": body.name,
    }


class BowlCompareIn(BaseModel):
    a: dict[str, Any]
    b: dict[str, Any]


@app.post("/api/bowl/compare")
async def api_bowl_compare(body: BowlCompareIn) -> dict[str, Any]:
    return compare_bowl_presets(body.a, body.b)


def main() -> None:
    import os

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
