"""Two-scale integrator orchestrating all physics modules."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from src.acoustic_stack import AcousticStack
from src.bioheat import Bioheat1D, BioheatParams, PiezoThermalRC
from src.driver import Driver, DriverOutput, DriverParams, duty_factor
from src.fsm_sonotrode import FSMState, SonotrodeFSM
from src.operator_motion import OperatorMotion
from src.piezo_bvd import BVDParams, PiezoBVD
from src.propagation import Propagation
from src.station import ProgramBlob, Station
from src.frequencies import (
    ALLOWED_F0_HZ,
    half_value_depth_m,
    suggested_piezo_thickness_m,
    validate_f0,
    wavelength_m,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class SimSnapshot:
    t_s: float
    state: str
    i_sata: float
    i_sapa: float
    p_ac: float
    p_bat: float
    r1: float
    contact: bool
    vswr: float
    t_piezo_c: float
    t_skin_surface_c: float
    soc: float
    t_remaining_s: float
    dose_peak: float
    motion_ok: bool
    gel_thickness_m: float
    x_half_m: float
    i_profile: list[float]
    t_profile: list[float]
    dose_profile: list[float]
    x_mm: list[float]
    burst_on: bool
    duty: float


@dataclass
class SimulationConfig:
    model: str = "SKINOVA_19"
    seed: int | None = 42
    dt_macro_s: float = 0.005  # 5 ms
    gel_present: bool = True
    path: str = "circle"
    force_n: float = 1.0
    duty_interpretation: str = "RATIO_ON_OFF"
    limit_domain: str = "SATA"
    enable_2d: bool = False
    i_set_override: float | None = None
    duration_override_s: float | None = None
    mode_override: str | None = None
    prf_hz: float = 100.0
    bat_capacity_wh: float = 2.5
    t_warn_c: float = 41.0
    t_off_c: float = 43.0
    stack_efficiency: float = 0.65
    vdrive_peak_v: float = 40.0
    pcb_drive_v: float = 40.0
    eta_elec: float = 0.7
    drive_level: float = 1.0
    p_elec_max_w: float = 8.0
    i_sense_window_ms: float = 2.0
    c0_nF: float = 1.5
    k_eff2: float | None = None
    q_m_air: float | None = None
    q_m_gel: float | None = None
    alpha_power_n: float | None = None
    motion_still_s: float = 2.0
    motion_eps: float = 0.05
    f0_hz_override: float | None = None  # sim-allowed {1,3,10,19} MHz


class Simulation:
    """Deterministic two-scale Skinova simulator."""

    def __init__(self, cfg: SimulationConfig | None = None) -> None:
        self.cfg = cfg or SimulationConfig()
        self.devices = _load_yaml("devices.yaml")
        self.programs = _load_yaml("programs.yaml")
        self.tissue = _load_yaml("tissue.yaml")
        self._rng = np.random.default_rng(self.cfg.seed)

        model = self.cfg.model
        model_cfg = self.devices["models"][model]
        default_f0 = float(model_cfg["f0_hz"])
        if self.cfg.f0_hz_override is not None:
            self.f0 = validate_f0(float(self.cfg.f0_hz_override))
        else:
            self.f0 = validate_f0(default_f0)
        self.f0_default_hz = default_f0
        era_cm2 = float(self.devices["sonotrode"]["era_cm2"])
        self.era_cm2 = era_cm2
        self.era_m2 = era_cm2 * 1e-4

        x_half_map = self.devices.get("half_value_depth_m", {})
        self.x_half = half_value_depth_m(self.f0, x_half_map)

        piezo_cfg = self.devices["piezo"]
        self.piezo = PiezoBVD(
            params=BVDParams(
                f0_hz=self.f0,
                c0_f=self.cfg.c0_nF * 1e-9,
                k_eff2=float(
                    self.cfg.k_eff2
                    if self.cfg.k_eff2 is not None
                    else piezo_cfg["k_eff2"]
                ),
                q_m_air=float(
                    self.cfg.q_m_air
                    if self.cfg.q_m_air is not None
                    else piezo_cfg["q_m_air"]
                ),
                q_m_gel=float(
                    self.cfg.q_m_gel
                    if self.cfg.q_m_gel is not None
                    else piezo_cfg["q_m_gel"]
                ),
                era_m2=self.era_m2,
            ),
            gel_present=self.cfg.gel_present,
        )
        self.driver = Driver(
            DriverParams(
                vdrive_peak_v=self.cfg.vdrive_peak_v,
                pcb_drive_v=self.cfg.pcb_drive_v,
                eta_elec=self.cfg.eta_elec,
                stack_efficiency=self.cfg.stack_efficiency,
                i_max_w_cm2=float(self.devices["sonotrode"]["i_max_w_cm2"]),
                era_cm2=era_cm2,
                limit_domain=self.cfg.limit_domain,
                p_ac_max_w=float(self.devices["sonotrode"]["p_ac_max_w"]),
                drive_level=self.cfg.drive_level,
                p_elec_max_w=self.cfg.p_elec_max_w,
                i_sense_window_ms=self.cfg.i_sense_window_ms,
            )
        )
        h_pzt = suggested_piezo_thickness_m(self.f0)
        self.stack = AcousticStack.default(h_pzt)
        self.stack.stack_efficiency = self.cfg.stack_efficiency
        self.stack.gel_present = self.cfg.gel_present

        self.prop = Propagation(
            f_hz=self.f0,
            x_half_m=self.x_half,
            era_m2=self.era_m2,
            enable_2d=self.cfg.enable_2d,
        )
        bh = BioheatParams(alpha_np_m=self.prop.alpha)
        self.bioheat = Bioheat1D(params=bh)
        th = self.devices.get("thermal_piezo", {})
        self.piezo_th = PiezoThermalRC(
            c_th=float(th.get("c_th_j_per_k", 8.0)),
            r_th=float(th.get("r_th_k_per_w", 12.0)),
            h_gel=float(th.get("h_gel_w_per_k", 0.8)),
            t_amb_c=float(th.get("t_amb_c", 25.0)),
        )
        has_sensors = "NTC" in model_cfg.get("sensors", []) or model == "SKINOVA_19"
        self.fsm = SonotrodeFSM(
            model=model,
            t_warn_c=self.cfg.t_warn_c,
            t_off_c=self.cfg.t_off_c,
            motion_still_s=self.cfg.motion_still_s,
            motion_eps=self.cfg.motion_eps,
            has_sensors=has_sensors,
        )
        self.station = Station()
        self.motion = OperatorMotion(
            path=self.cfg.path,
            force_n=self.cfg.force_n,
            seed=self.cfg.seed,
        )
        self.soc = 1.0
        self.bat_capacity_wh = self.cfg.bat_capacity_wh
        self.t_s = 0.0
        self.duty_interpretation = self.cfg.duty_interpretation
        self._burst_phase = 0.0
        self.history: list[SimSnapshot] = []
        self._last_drv = None
        self._last_motion = None

    def list_programs(self) -> list[dict[str, Any]]:
        return list(self.programs.get(self.cfg.model, []))

    def load_program(self, program_id: int) -> ProgramBlob:
        progs = self.list_programs()
        match = next((p for p in progs if p["id"] == program_id), None)
        if match is None:
            raise ValueError(f"Unknown program id {program_id} for {self.cfg.model}")
        i_set = self.cfg.i_set_override if self.cfg.i_set_override is not None else float(match["i_sata_w_cm2"])
        dur = self.cfg.duration_override_s if self.cfg.duration_override_s is not None else float(match["duration_s"])
        mode = self.cfg.mode_override or match["mode"]
        blob = ProgramBlob(
            program_id=match["id"],
            name=match["name"],
            f0_hz=self.f0,
            mode=mode,
            i_set=min(i_set, 0.5),
            duration_s=min(dur, 720.0),
            prf_hz=float(match.get("prf_hz", self.cfg.prf_hz)),
            zones=list(match.get("zones", ["face"])),
        )
        self.station.write(self.fsm, blob)
        return blob

    def set_gel(self, present: bool) -> None:
        self.cfg.gel_present = present
        self.piezo.gel_present = present
        self.stack.gel_present = present

    def set_path(self, path: str) -> None:
        self.cfg.path = path
        self.motion.set_path(path)

    def start(self) -> bool:
        if self.fsm.nvm.program_id is None:
            progs = self.list_programs()
            if progs:
                self.load_program(progs[0]["id"])
        self.fsm.undock()
        return self.fsm.start()

    def pause(self) -> None:
        self.fsm.pause()

    def reset(self) -> None:
        self.t_s = 0.0
        self.soc = 1.0
        self.bioheat.reset()
        self.piezo_th.reset()
        self.history.clear()
        self.fsm.reset_session()
        self._burst_phase = 0.0

    def _duty(self) -> float:
        return duty_factor(self.fsm.nvm.mode, self.duty_interpretation)

    def _burst_on(self, dt_s: float) -> bool:
        """Rectangular burst envelope at PRF; carrier is behavioural (macro only)."""
        duty = self._duty()
        if duty >= 0.999:
            return True
        prf = max(50.0, min(1000.0, self.fsm.nvm.prf_hz))
        period = 1.0 / prf
        self._burst_phase = (self._burst_phase + dt_s) % period
        return self._burst_phase < period * duty

    def step(self, dt_s: float | None = None) -> SimSnapshot:
        dt = dt_s if dt_s is not None else self.cfg.dt_macro_s
        motion = self.motion.sample(dt)
        self._last_motion = motion

        gel_present = self.cfg.gel_present
        self.piezo.gel_present = gel_present
        self.piezo.gel_fraction = 1.0 if gel_present else 0.0
        self.stack.gel_thickness_m = motion.gel_thickness_m
        self.stack.gel_present = gel_present

        duty = self._duty()
        emitting_state = self.fsm.state == FSMState.RUNNING
        burst = self._burst_on(dt) if emitting_state else False

        i_set = self.fsm.nvm.i_set
        drv = self.driver.regulate(
            self.piezo,
            i_set,
            duty,
            force_air=not gel_present,
        )
        # Gate acoustic output by burst envelope
        if not burst or not emitting_state:
            if gel_present and emitting_state:
                # Off-phase of burst: no acoustic, minimal standby draw
                drv = DriverOutput(
                    vdrive_peak=drv.vdrive_peak,
                    i_sata_w_cm2=0.0,
                    i_sapa_w_cm2=0.0,
                    p_ac_w=0.0,
                    p_elec_w=0.05,
                    p_bat_w=0.05,
                    p_piezo_loss_w=0.02,
                    eta_ea=drv.eta_ea,
                    vswr=drv.vswr,
                    contact=drv.contact,
                )
            elif not gel_present and emitting_state:
                pass  # keep air-load heating from force_air regulate()
            else:
                drv = DriverOutput(
                    vdrive_peak=0.0,
                    i_sata_w_cm2=0.0,
                    i_sapa_w_cm2=0.0,
                    p_ac_w=0.0,
                    p_elec_w=0.0,
                    p_bat_w=0.0,
                    p_piezo_loss_w=0.0,
                    eta_ea=0.0,
                    vswr=1.0,
                    contact=gel_present,
                )

        # Without gel: stack transmission is zero → force P_ac / I_SATA to 0
        if not gel_present:
            drv = DriverOutput(
                vdrive_peak=drv.vdrive_peak,
                i_sata_w_cm2=0.0,
                i_sapa_w_cm2=0.0,
                p_ac_w=0.0,
                p_elec_w=drv.p_elec_w,
                p_bat_w=drv.p_bat_w,
                p_piezo_loss_w=drv.p_piezo_loss_w,
                eta_ea=0.0,
                vswr=drv.vswr,
                contact=False,
            )

        self._last_drv = drv
        bvd = self.piezo.evaluate()

        # Bioheat + piezo thermal
        moving = motion.speed_m_s >= 0.002
        i_for_heat = drv.i_sata_w_cm2 if burst and emitting_state else 0.0
        # For SATA display we report time-averaged target when running with gel
        i_sata_display = 0.0
        if emitting_state and gel_present and drv.contact:
            i_sata_display = min(i_set, 0.5)

        bh = self.bioheat.step(i_for_heat if gel_present else 0.0, dt, moving=moving)
        t_skin = float(bh.t_c[0])
        t_piezo = self.piezo_th.step(
            drv.p_piezo_loss_w,
            dt,
            t_skin_c=t_skin,
            gel_present=gel_present,
        )

        # Battery discharge
        if drv.p_bat_w > 0 and self.bat_capacity_wh > 0:
            self.soc = max(0.0, self.soc - (drv.p_bat_w * dt / 3600.0) / self.bat_capacity_wh)

        # Docked charging
        if self.fsm.docked:
            self.soc = self.station.charge(self.fsm, self.soc, dt)

        contact = bool(drv.contact and gel_present)
        self.fsm.tick(
            dt,
            contact=contact if emitting_state or self.fsm.state == FSMState.PAUSED_NO_CONTACT else True,
            t_piezo_c=t_piezo,
            motion_variance=motion.accel_var,
            soc=self.soc,
            emitting=burst and emitting_state and contact,
        )

        # When RUNNING but we used contact gate: if no contact, FSM already paused
        # Advance timer only when actually emitting into tissue
        # (FSM.tick already handles t_remaining when emitting=True)

        self.t_s += dt
        prof = self.prop.profile(i_sata_display if i_sata_display > 0 else max(i_for_heat, 1e-9))

        snap = SimSnapshot(
            t_s=self.t_s,
            state=self.fsm.state.value,
            i_sata=i_sata_display if emitting_state and gel_present else drv.i_sata_w_cm2,
            i_sapa=drv.i_sapa_w_cm2,
            p_ac=min(drv.p_ac_w if gel_present else 0.0, 1.5),
            p_bat=drv.p_bat_w,
            r1=bvd.r1,
            contact=contact,
            vswr=drv.vswr,
            t_piezo_c=t_piezo,
            t_skin_surface_c=t_skin,
            soc=self.soc,
            t_remaining_s=self.fsm.nvm.t_remaining_s,
            dose_peak=float(np.max(bh.dose_j_m3)),
            motion_ok=motion.accel_var >= self.cfg.motion_eps,
            gel_thickness_m=motion.gel_thickness_m,
            x_half_m=self.x_half,
            i_profile=(prof.i_w_m2 / 1e4).tolist(),  # W/cm²
            t_profile=bh.t_c.tolist(),
            dose_profile=bh.dose_j_m3.tolist(),
            x_mm=(prof.x_m * 1e3).tolist(),
            burst_on=burst,
            duty=duty,
        )
        self.history.append(snap)
        return snap

    def run_for(self, seconds: float, dt_s: float | None = None) -> list[SimSnapshot]:
        dt = dt_s if dt_s is not None else self.cfg.dt_macro_s
        n = int(math_ceil(seconds / dt))
        out: list[SimSnapshot] = []
        for _ in range(n):
            out.append(self.step(dt))
            if self.fsm.state in (
                FSMState.FINISHED,
                FSMState.FAULT_OVERTEMP,
                FSMState.FAULT_MOTION,
                FSMState.FAULT_BATTERY,
                FSMState.LOCKED_NEEDS_STATION,
            ):
                break
        return out

    def status_dict(self) -> dict[str, Any]:
        snap = self.history[-1] if self.history else None
        return {
            "model": self.cfg.model,
            "f0_hz": self.f0,
            "f0_default_hz": self.f0_default_hz,
            "allowed_f0_hz": sorted(ALLOWED_F0_HZ),
            "f0_hint": (
                "1/3 MHz are clinical/LDM-class simulation options; "
                "home firmware defaults remain 10/19 MHz."
            ),
            "state": self.fsm.state.value,
            "nvm": self.fsm.nvm.to_dict(),
            "soc": self.soc,
            "t_s": self.t_s,
            "calibration_preset": bool(self.programs.get("CALIBRATION_PRESET", True)),
            "t_warn_c": self.cfg.t_warn_c,
            "t_off_c": self.cfg.t_off_c,
            "bat_capacity_wh": self.bat_capacity_wh,
            "x_half_m": self.x_half,
            "lambda_m": self.prop.profile(0.1).lambda_m,
            "z_n_m": self.prop.profile(0.1).z_n_m,
            "snapshot": None if snap is None else snap.__dict__,
            "station": {
                "dimensions_mm": list(self.station.specs.dimensions_mm),
                "mass_kg": self.station.specs.mass_kg,
                "power_va": self.station.specs.power_va,
            },
            "bvd": {
                "c0_nF": self.cfg.c0_nF,
                "k_eff2": self.piezo.params.k_eff2,
                "q_m_air": self.piezo.params.q_m_air,
                "q_m_gel": self.piezo.params.q_m_gel,
                "c1_nF": self.piezo.params.c1_f * 1e9,
                "l1_uH": self.piezo.params.l1_h * 1e6,
                "r_m": self.piezo.params.r_m,
            },
            "alpha_power_n": self.cfg.alpha_power_n
            if self.cfg.alpha_power_n is not None
            else float(self.tissue.get("alpha_power_n", 1.2)),
            "stack_efficiency": self.cfg.stack_efficiency,
            "vdrive_peak_v": self.cfg.vdrive_peak_v,
            "pcb_drive_v": self.cfg.pcb_drive_v,
            "eta_elec": self.cfg.eta_elec,
            "drive_level": self.cfg.drive_level,
            "p_elec_max_w": self.cfg.p_elec_max_w,
            "i_sense_window_ms": self.cfg.i_sense_window_ms,
        }


def math_ceil(x: float) -> int:
    return int(math.ceil(x))
