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


def main() -> None:
    import os

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
