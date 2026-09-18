"""Time-dependent lumped thermal–acoustic coupling for the Akustik-Schale.

CALIBRATION_PRESET — educational model, not factory firmware.
Each macro step: acoustics → losses → heat → ΔT → property change → acoustics.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np

from src.acoustic_bowl import AcousticBowl, _load_bowl_yaml


DURATION_MAX_S = 720.0  # 12 min
DURATION_MIN_S = 1.0
DT_MIN_S = 0.05
DT_MAX_S = 0.5


@dataclass
class ThermalParams:
    """Lumped thermal nodes + temperature-coupling coefficients (calib)."""

    t_amb_c: float = 25.0
    t0_c: float = 25.0
    t_warn_c: float = 55.0
    t_off_c: float = 70.0
    c_piezo_j_kgk: float = 350.0
    c_glue_j_kgk: float = 1500.0
    c_ti_j_kgk: float = 526.0
    c_load_j_kgk: float = 3400.0
    g_piezo_glue_w_k: float = 0.35
    g_glue_ti_w_k: float = 0.50
    g_ti_load_w_k: float = 0.20
    h_conv_w_m2k: float = 40.0
    k_glue_loss_per_c: float = 0.025
    k_eff_drop_per_c: float = 0.0018
    k_kt_drop_per_c: float = 0.0006
    k_res_shift_hz_per_c: float = -150.0
    include_load_node: bool = False
    derate_smooth: bool = True
    duration_default_s: float = 60.0
    duration_max_s: float = DURATION_MAX_S
    dt_default_s: float = 0.1

    def clip(self) -> "ThermalParams":
        self.t_amb_c = float(np.clip(self.t_amb_c, 10.0, 45.0))
        self.t0_c = float(np.clip(self.t0_c, 10.0, 45.0))
        self.t_warn_c = float(np.clip(self.t_warn_c, 35.0, 90.0))
        self.t_off_c = float(np.clip(self.t_off_c, self.t_warn_c + 1.0, 110.0))
        self.h_conv_w_m2k = float(np.clip(self.h_conv_w_m2k, 1.0, 120.0))
        self.g_piezo_glue_w_k = float(np.clip(self.g_piezo_glue_w_k, 0.01, 10.0))
        self.g_glue_ti_w_k = float(np.clip(self.g_glue_ti_w_k, 0.01, 10.0))
        self.g_ti_load_w_k = float(np.clip(self.g_ti_load_w_k, 0.0, 5.0))
        self.k_glue_loss_per_c = float(np.clip(self.k_glue_loss_per_c, 0.0, 0.2))
        self.k_eff_drop_per_c = float(np.clip(self.k_eff_drop_per_c, 0.0, 0.05))
        self.k_kt_drop_per_c = float(np.clip(self.k_kt_drop_per_c, 0.0, 0.02))
        return self


def default_thermal_params(cfg: dict[str, Any] | None = None) -> ThermalParams:
    cfg = cfg or _load_bowl_yaml()
    th = cfg.get("thermal") or {}
    kwargs: dict[str, Any] = {}
    for f in fields(ThermalParams):
        if f.name in th and th[f.name] is not None:
            kwargs[f.name] = th[f.name]
    return ThermalParams(**kwargs).clip()


def thermal_params_from_dict(
    data: dict[str, Any] | None,
    base: ThermalParams | None = None,
) -> ThermalParams:
    p = base or default_thermal_params()
    out = ThermalParams(**{f.name: getattr(p, f.name) for f in fields(ThermalParams)})
    if not data:
        return out.clip()
    for f in fields(ThermalParams):
        if f.name in data and data[f.name] is not None:
            if f.name == "include_load_node" or f.name == "derate_smooth":
                setattr(out, f.name, bool(data[f.name]))
            else:
                setattr(out, f.name, float(data[f.name]))
    return out.clip()


def suggest_dt(duration_s: float) -> float:
    """Adaptive macro timestep in [0.05, 0.5] s by duration."""
    d = float(duration_s)
    if d <= 10.0:
        return 0.05
    if d <= 30.0:
        return 0.1
    if d <= 60.0:
        return 0.15
    if d <= 120.0:
        return 0.2
    if d <= 300.0:
        return 0.25
    return 0.5


def derate_factor(t_piezo_c: float, th: ThermalParams) -> float:
    """Drive derate: 1 below T_warn → 0 at/above T_off (smooth or hard)."""
    if t_piezo_c <= th.t_warn_c:
        return 1.0
    if t_piezo_c >= th.t_off_c:
        return 0.0
    span = max(th.t_off_c - th.t_warn_c, 1e-6)
    x = (t_piezo_c - th.t_warn_c) / span
    if th.derate_smooth:
        # Smooth cosine roll-off
        return float(0.5 * (1.0 + math.cos(math.pi * x)))
    return 1.0  # hard: stay full until T_off


def _heat_capacities(bowl: AcousticBowl, th: ThermalParams) -> dict[str, float]:
    """C = ρ · c · V from layer thickness × area (ERA / piezo).

    Thin glue has tiny geometric volume — we add a small effective bond-zone
    floor and count cup side-walls in the Ti mass / cooling area (calib).
    """
    p = bowl.params
    mats = bowl._materials()
    h_pzt = p.resolved_piezo_thickness(mats["pzt"].c_m_s)
    a_pzt = math.pi * (min(p.piezo_diameter_m, p.cup_inner_diameter_m) / 2.0) ** 2
    a_ti = math.pi * (p.ti_diameter_m / 2.0) ** 2
    a_glue = a_pzt
    # Cup outer surface for convection (bottom + approximate side wall)
    wall_area = math.pi * p.cup_outer_diameter_m * max(p.cup_depth_m, 1e-3)
    a_cool = a_ti + wall_area

    v_pzt = a_pzt * h_pzt
    # Effective glue bond zone ≥ 50 µm participating thickness (calib floor)
    v_glue = a_glue * max(p.glue_thickness_m, 5e-5)
    v_ti_bottom = a_ti * max(p.ti_thickness_m, 1e-5)
    # Side-wall Ti mass contribution (approx cylindrical shell)
    r_o = p.cup_outer_diameter_m / 2.0
    r_i = max(p.cup_inner_diameter_m / 2.0, 1e-4)
    v_ti_wall = math.pi * (r_o**2 - r_i**2) * max(p.cup_depth_m, 1e-3)
    v_ti = v_ti_bottom + 0.5 * v_ti_wall
    v_load = a_ti * max(p.gel_thickness_m, 2e-4)

    c_pzt = mats["pzt"].rho_kg_m3 * th.c_piezo_j_kgk * v_pzt
    c_glue = mats["glue"].rho_kg_m3 * th.c_glue_j_kgk * v_glue
    c_ti = mats["titanium"].rho_kg_m3 * th.c_ti_j_kgk * v_ti
    # Floors keep Euler/substep stable for educational calib model
    c_glue = max(c_glue, 0.08)
    c_pzt = max(c_pzt, 0.15)
    c_ti = max(c_ti, 0.40)
    rho_load = 1010.0
    c_load = max(rho_load * th.c_load_j_kgk * v_load, 0.20)
    return {
        "piezo": c_pzt,
        "glue": c_glue,
        "ti": c_ti,
        "load": c_load,
        "area_piezo": a_pzt,
        "area_ti": a_ti,
        "area_cool": a_cool,
    }


def thermal_help(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or _load_bowl_yaml()
    th = default_thermal_params(cfg)
    return {
        "calibration": True,
        "label": (cfg.get("thermal") or {}).get("label", ""),
        "defaults": asdict(th),
        "ranges": cfg.get("ranges_thermal") or {
            "duration_s": [1, 720],
            "dt_s": [0.05, 0.5],
            "t_amb_c": [15, 40],
            "t_warn_c": [40, 80],
            "t_off_c": [50, 100],
            "h_conv_w_m2k": [5, 80],
            "k_glue_loss_per_c": [0, 0.1],
            "k_eff_drop_per_c": [0, 0.02],
        },
        "duration_presets_s": [10, 30, 60, 120, 300],
        "notes": [
            "Lumped nodes T_piezo, T_glue, T_ti (+ optional T_load); T_amb convection.",
            "Heat from energy partition each step; glue α and stack η couple back to acoustics.",
            "Drive derates between T_warn and T_off (calib, not firmware).",
        ],
    }


def run_bowl_transient(
    bowl: AcousticBowl,
    duration_s: float,
    dt_s: float | None = None,
    thermal: ThermalParams | None = None,
) -> dict[str, Any]:
    """Coupled thermal–acoustic time series (calibration model).

    Returns series + summary. Restores bowl.params after run.
    """
    th = (thermal or default_thermal_params(bowl.cfg)).clip()
    duration_s = float(np.clip(duration_s, DURATION_MIN_S, th.duration_max_s))
    if dt_s is None or dt_s <= 0:
        dt = suggest_dt(duration_s)
    else:
        dt = float(np.clip(dt_s, DT_MIN_S, DT_MAX_S))
    # Cap step count for UI responsiveness (~ max ~2400 points)
    max_steps = 2400
    n_steps = int(math.ceil(duration_s / dt))
    if n_steps > max_steps:
        dt = duration_s / max_steps
        dt = float(np.clip(dt, DT_MIN_S, DT_MAX_S))
        n_steps = int(math.ceil(duration_s / dt))

    caps = _heat_capacities(bowl, th)
    c_p, c_g, c_ti, c_ld = caps["piezo"], caps["glue"], caps["ti"], caps["load"]
    a_p, a_ti = caps["area_piezo"], caps["area_ti"]
    a_cool = caps.get("area_cool", a_ti)
    g_pg = th.g_piezo_glue_w_k
    g_gt = th.g_glue_ti_w_k
    g_tl = th.g_ti_load_w_k if th.include_load_node else 0.0
    h = th.h_conv_w_m2k
    t_amb = th.t_amb_c
    # Explicit stability: substep so Fo-like dt*G/C stays < ~0.35
    g_max = max(g_pg, g_gt, g_tl, h * a_cool, h * a_p, 1e-6)
    c_min = min(c_p, c_g, c_ti, c_ld)
    dt_therm_max = 0.35 * c_min / g_max
    n_sub = max(1, int(math.ceil(dt / max(dt_therm_max, 1e-6))))
    n_sub = min(n_sub, 80)
    dt_sub = dt / n_sub

    p0 = bowl.params
    base_drive = float(p0.drive_level)
    base_eff = float(p0.stack_efficiency)
    base_kt = float(p0.kt)
    base_glue_scale = float(getattr(p0, "glue_attn_scale", 1.0) or 1.0)

    t_p = th.t0_c
    t_g = th.t0_c
    t_ti = th.t0_c
    t_ld = th.t0_c

    t_list: list[float] = []
    tp_list: list[float] = []
    tg_list: list[float] = []
    tti_list: list[float] = []
    tld_list: list[float] = []
    pac_list: list[float] = []
    eta_list: list[float] = []
    drive_list: list[float] = []
    glue_f_list: list[float] = []
    p_glue_list: list[float] = []
    p_pzt_list: list[float] = []
    p_ti_list: list[float] = []
    derate_list: list[float] = []
    derate_events: list[dict[str, Any]] = []
    derate_active = False

    try:
        for i in range(n_steps + 1):
            t = min(i * dt, duration_s)
            d_factor = derate_factor(t_p, th)
            drive_eff = base_drive * d_factor
            glue_scale = max(
                0.4,
                base_glue_scale * (1.0 + th.k_glue_loss_per_c * (t_g - th.t0_c)),
            )
            stack_eff = max(
                0.15,
                base_eff * (1.0 - th.k_eff_drop_per_c * (t_p - th.t0_c)),
            )
            kt_eff = max(
                0.2,
                base_kt * (1.0 - th.k_kt_drop_per_c * (t_p - th.t0_c)),
            )

            p0.drive_level = drive_eff
            p0.stack_efficiency = stack_eff
            p0.kt = kt_eff
            p0.glue_attn_scale = glue_scale

            e = bowl.energy_partition()

            if d_factor < 0.999 and not derate_active:
                derate_events.append(
                    {
                        "t_s": t,
                        "t_piezo_c": t_p,
                        "derate": d_factor,
                        "kind": "engage",
                    }
                )
                derate_active = True
            elif d_factor >= 0.999 and derate_active:
                derate_events.append(
                    {
                        "t_s": t,
                        "t_piezo_c": t_p,
                        "derate": d_factor,
                        "kind": "release",
                    }
                )
                derate_active = False

            t_list.append(t)
            tp_list.append(t_p)
            tg_list.append(t_g)
            tti_list.append(t_ti)
            tld_list.append(t_ld)
            pac_list.append(float(e.p_radiated_w))
            eta_list.append(float(e.efficiency))
            drive_list.append(float(drive_eff))
            glue_f_list.append(float(glue_scale))
            p_glue_list.append(float(e.p_glue_loss_w))
            p_pzt_list.append(float(e.p_piezo_heat_w))
            p_ti_list.append(float(e.p_ti_loss_w))
            derate_list.append(float(d_factor))

            if i >= n_steps:
                break

            # Lumped RC thermal substeps (powers held constant over macro dt)
            for _ in range(n_sub):
                q_p = e.p_piezo_heat_w + g_pg * (t_g - t_p) + h * a_p * (t_amb - t_p)
                q_g = e.p_glue_loss_w + g_pg * (t_p - t_g) + g_gt * (t_ti - t_g)
                q_ti = (
                    e.p_ti_loss_w
                    + g_gt * (t_g - t_ti)
                    + g_tl * (t_ld - t_ti)
                    + h * a_cool * (t_amb - t_ti)
                )
                q_ld = 0.0
                if th.include_load_node:
                    q_ld = (
                        0.15 * e.p_radiated_w
                        + g_tl * (t_ti - t_ld)
                        + h * a_ti * (t_amb - t_ld)
                    )
                t_p = t_p + dt_sub * q_p / c_p
                t_g = t_g + dt_sub * q_g / c_g
                t_ti = t_ti + dt_sub * q_ti / c_ti
                if th.include_load_node:
                    t_ld = t_ld + dt_sub * q_ld / c_ld
                else:
                    t_ld = t_amb
                # Soft clamp (calib) — avoid runaway if user sets extreme coeffs
                t_p = float(np.clip(t_p, t_amb - 5.0, 250.0))
                t_g = float(np.clip(t_g, t_amb - 5.0, 250.0))
                t_ti = float(np.clip(t_ti, t_amb - 5.0, 250.0))
                t_ld = float(np.clip(t_ld, t_amb - 5.0, 250.0))
    finally:
        p0.drive_level = base_drive
        p0.stack_efficiency = base_eff
        p0.kt = base_kt
        p0.glue_attn_scale = base_glue_scale

    dT_piezo = float(max(tp_list) - th.t0_c) if tp_list else 0.0
    dT_glue = float(max(tg_list) - th.t0_c) if tg_list else 0.0
    dT_ti = float(max(tti_list) - th.t0_c) if tti_list else 0.0
    res_shift_end = th.k_res_shift_hz_per_c * (tp_list[-1] - th.t0_c) if tp_list else 0.0

    return {
        "calibration": True,
        "label": "CALIBRATION_PRESET — thermal–acoustic transient (not factory firmware)",
        "duration_s": duration_s,
        "dt_s": dt,
        "n_steps": n_steps,
        "thermal": asdict(th),
        "capacities_j_k": {
            "piezo": c_p,
            "glue": c_g,
            "ti": c_ti,
            "load": c_ld,
        },
        "series": {
            "t_s": t_list,
            "T_piezo_c": tp_list,
            "T_glue_c": tg_list,
            "T_ti_c": tti_list,
            "T_load_c": tld_list,
            "P_ac_w": pac_list,
            "eta": eta_list,
            "drive_level": drive_list,
            "derate": derate_list,
            "glue_loss_factor": glue_f_list,
            "P_glue_loss_w": p_glue_list,
            "P_piezo_heat_w": p_pzt_list,
            "P_ti_loss_w": p_ti_list,
        },
        "summary": {
            "dT_piezo_c": dT_piezo,
            "dT_glue_c": dT_glue,
            "dT_ti_c": dT_ti,
            "T_piezo_max_c": float(max(tp_list)) if tp_list else th.t0_c,
            "T_glue_max_c": float(max(tg_list)) if tg_list else th.t0_c,
            "T_ti_max_c": float(max(tti_list)) if tti_list else th.t0_c,
            "P_ac_start_w": float(pac_list[0]) if pac_list else 0.0,
            "P_ac_end_w": float(pac_list[-1]) if pac_list else 0.0,
            "eta_start": float(eta_list[0]) if eta_list else 0.0,
            "eta_end": float(eta_list[-1]) if eta_list else 0.0,
            "derate_min": float(min(derate_list)) if derate_list else 1.0,
            "derate_engaged": bool(derate_events),
            "derate_events": derate_events,
            "resonance_shift_end_hz": float(res_shift_end),
            "glue_loss_factor_end": float(glue_f_list[-1]) if glue_f_list else 1.0,
        },
    }
