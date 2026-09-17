"""Acoustic bowl (чаша) multilayer simulation: PZT → glue → Ti → gel → tissue.

1D transfer-matrix / transmission-line model for the titanium face/bowl stack.
Unpublished geometry lives under CALIBRATION_PRESET (config/calibration_bowl.yaml)
and is never presented as factory data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

# Hard manufacturer anchors (immutable)
ERA_CM2 = 3.0
ERA_M2 = ERA_CM2 * 1e-4
I_MAX_W_CM2 = 0.5
P_AC_MAX_W = 1.5
C_TISSUE = 1540.0
Z_GEL_MRAYL = 1.5
Z_AIR_RAYL = 400.0


def _load_bowl_yaml() -> dict[str, Any]:
    path = CONFIG / "calibration_bowl.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def suggested_piezo_thickness(f0_hz: float, c_pzt: float = 4200.0) -> float:
    """λ/2 thickness-mode suggestion: h = c / (2 f0)."""
    return c_pzt / (2.0 * f0_hz)


def era_equivalent_diameter_m(era_cm2: float = ERA_CM2) -> float:
    return 2.0 * math.sqrt((era_cm2 * 1e-4) / math.pi)


def wavelength(f_hz: float, c: float = C_TISSUE) -> float:
    return c / f_hz


@dataclass
class Material:
    name: str
    rho_kg_m3: float
    c_m_s: float
    z_mrayl: float
    attenuation_np_m_mhz: float = 0.0
    key: str = ""

    @property
    def z_rayl(self) -> float:
        return self.z_mrayl * 1e6


@dataclass
class BowlLayer:
    name: str
    material: Material
    thickness_m: float
    diameter_m: float | None = None

    def area_m2(self) -> float:
        d = self.diameter_m
        if d is None or d <= 0:
            return ERA_M2
        return math.pi * (d / 2.0) ** 2


@dataclass
class BowlParams:
    f0_hz: float = 19e6
    drive_level: float = 1.0
    load: str = "gel_tissue"  # air | gel | gel_tissue
    piezo_material: str = "pzt8"
    glue_material: str = "glue_epoxy"
    ti_thickness_m: float = 3e-4
    ti_diameter_m: float = 0.01954
    piezo_thickness_m: float | None = None
    piezo_diameter_m: float = 0.018
    glue_thickness_m: float = 1e-5
    gel_thickness_m: float = 3e-4
    era_cm2: float = ERA_CM2
    calibration: bool = True

    def resolved_piezo_thickness(self, c_pzt: float) -> float:
        if self.piezo_thickness_m is not None and self.piezo_thickness_m > 0:
            return float(self.piezo_thickness_m)
        return suggested_piezo_thickness(self.f0_hz, c_pzt)


@dataclass
class InterfaceState:
    name: str
    pressure_pa: complex
    velocity_m_s: complex
    intensity_w_m2: float


@dataclass
class SpectrumPoint:
    f_hz: float
    t_intensity: float
    r_intensity: float
    z_in_real: float
    z_in_imag: float
    z_in_mag: float


@dataclass
class EnergyPartition:
    p_drive_w: float
    p_radiated_w: float
    p_glue_loss_w: float
    p_piezo_heat_w: float
    p_ti_loss_w: float
    efficiency: float


@dataclass
class BowlResult:
    params: dict[str, Any]
    f0_hz: float
    t_at_f0: float
    r_at_f0: float
    z_in_at_f0: complex
    resonance_hz: float
    energy: EnergyPartition
    interfaces: list[InterfaceState]
    layers_schematic: list[dict[str, Any]]
    calibration: bool = True


def material_from_cfg(key: str, cfg: dict[str, Any] | None = None) -> Material:
    cfg = cfg or _load_bowl_yaml()
    mats = cfg["materials"]
    if key not in mats:
        raise KeyError(f"Unknown material '{key}'")
    m = mats[key]
    return Material(
        name=str(m["name"]),
        rho_kg_m3=float(m["rho_kg_m3"]),
        c_m_s=float(m["c_m_s"]),
        z_mrayl=float(m["z_mrayl"]),
        attenuation_np_m_mhz=float(m.get("attenuation_np_m_mhz", 0.0)),
        key=key,
    )


def default_bowl_params(cfg: dict[str, Any] | None = None) -> BowlParams:
    cfg = cfg or _load_bowl_yaml()
    d = cfg["defaults"]
    piezo_h = d.get("piezo_thickness_m")
    return BowlParams(
        f0_hz=float(d["f0_hz"]),
        drive_level=float(d["drive_level"]),
        load=str(d["load"]),
        piezo_material=str(d["piezo_material"]),
        glue_material=str(d["glue_material"]),
        ti_thickness_m=float(d["ti_thickness_m"]),
        ti_diameter_m=float(d["ti_diameter_m"]),
        piezo_thickness_m=None if piezo_h is None else float(piezo_h),
        piezo_diameter_m=float(d["piezo_diameter_m"]),
        glue_thickness_m=float(d["glue_thickness_m"]),
        gel_thickness_m=float(d["gel_thickness_m"]),
        era_cm2=float(cfg.get("anchors", {}).get("era_cm2", ERA_CM2)),
        calibration=bool(cfg.get("CALIBRATION_PRESET", True)),
    )


def params_help(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or _load_bowl_yaml()
    mats: dict[str, Any] = {}
    for k, m in cfg["materials"].items():
        mats[k] = {
            "name": m["name"],
            "z_mrayl": m["z_mrayl"],
            "c_m_s": m["c_m_s"],
            "rho_kg_m3": m["rho_kg_m3"],
            "help": m.get("help", ""),
        }
    return {
        "calibration": bool(cfg.get("CALIBRATION_PRESET", True)),
        "label": cfg.get("label", ""),
        "anchors": cfg.get("anchors", {}),
        "ranges": cfg.get("ranges", {}),
        "materials": mats,
        "glue_materials": [k for k in mats if k.startswith("glue")],
        "piezo_materials": [k for k in mats if k.startswith("pzt")],
        "notes": cfg.get("notes", []),
        "suggested_piezo_thickness_m": {
            "10MHz": suggested_piezo_thickness(10e6),
            "19MHz": suggested_piezo_thickness(19e6),
        },
        "d_eq_mm": era_equivalent_diameter_m() * 1e3,
    }


class AcousticBowl:
    """Multilayer transfer-matrix bowl simulator."""

    def __init__(
        self,
        params: BowlParams | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        self.cfg = cfg or _load_bowl_yaml()
        self.params = params or default_bowl_params(self.cfg)

    def _materials(self) -> dict[str, Material]:
        p = self.params
        return {
            "pzt": material_from_cfg(p.piezo_material, self.cfg),
            "glue": material_from_cfg(p.glue_material, self.cfg),
            "titanium": material_from_cfg("titanium", self.cfg),
            "gel": material_from_cfg("gel", self.cfg),
            "tissue": material_from_cfg("tissue", self.cfg),
            "air": material_from_cfg("air", self.cfg),
        }

    def build_layers(self) -> list[BowlLayer]:
        p = self.params
        mats = self._materials()
        h_pzt = p.resolved_piezo_thickness(mats["pzt"].c_m_s)
        d_piezo = min(p.piezo_diameter_m, p.ti_diameter_m)
        layers = [
            BowlLayer("pzt", mats["pzt"], h_pzt, d_piezo),
            BowlLayer("glue", mats["glue"], max(p.glue_thickness_m, 1e-9), d_piezo),
            BowlLayer("titanium", mats["titanium"], p.ti_thickness_m, p.ti_diameter_m),
        ]
        load = p.load.lower()
        if load == "air":
            layers.append(BowlLayer("air", mats["air"], 0.01, p.ti_diameter_m))
        elif load == "gel":
            layers.append(BowlLayer("gel", mats["gel"], p.gel_thickness_m, p.ti_diameter_m))
        else:
            layers.append(BowlLayer("gel", mats["gel"], p.gel_thickness_m, p.ti_diameter_m))
            layers.append(BowlLayer("tissue", mats["tissue"], 0.005, p.ti_diameter_m))
        return layers

    def _layer_matrix(self, layer: BowlLayer, f_hz: float) -> np.ndarray:
        mat = layer.material
        z = mat.z_rayl
        alpha = mat.attenuation_np_m_mhz * (f_hz / 1e6)
        k = 2.0 * math.pi * f_hz / mat.c_m_s - 1j * alpha
        kd = k * layer.thickness_m
        cl = np.cos(kd)
        sl = np.sin(kd)
        a = cl
        b = 1j * z * sl
        c = (1j * sl / z) if z > 0 else 0j
        d = cl
        return np.array([[a, b], [c, d]], dtype=complex)

    def transfer_matrix(
        self, f_hz: float, layers: list[BowlLayer] | None = None
    ) -> np.ndarray:
        layers = layers or self.build_layers()
        t = np.eye(2, dtype=complex)
        for layer in layers:
            t = t @ self._layer_matrix(layer, f_hz)
        return t

    def input_impedance(
        self, f_hz: float, layers: list[BowlLayer] | None = None
    ) -> complex:
        layers = layers or self.build_layers()
        if not layers:
            return complex(Z_AIR_RAYL)
        z_load = layers[-1].material.z_rayl
        if len(layers) == 1:
            return complex(z_load)
        t = np.eye(2, dtype=complex)
        for layer in layers[:-1]:
            t = t @ self._layer_matrix(layer, f_hz)
        a, b = t[0, 0], t[0, 1]
        c, d = t[1, 0], t[1, 1]
        denom = c * z_load + d
        if abs(denom) < 1e-30:
            return complex(1e12)
        return (a * z_load + b) / denom

    def transmission_reflection(
        self, f_hz: float, layers: list[BowlLayer] | None = None
    ) -> tuple[float, float, complex]:
        layers = layers or self.build_layers()
        zin = self.input_impedance(f_hz, layers)
        if layers[-1].name == "air" or layers[-1].material.z_mrayl < 0.01:
            return 0.0, 1.0, zin

        z_in_med = layers[0].material.z_rayl
        z_out = layers[-1].material.z_rayl
        t = self.transfer_matrix(f_hz, layers)
        a, b = t[0, 0], t[0, 1]
        c, d = t[1, 0], t[1, 1]
        denom = a * z_out + b + c * z_in_med * z_out + d * z_in_med
        if abs(denom) < 1e-30:
            return 0.0, 1.0, zin
        t_p = 2.0 * z_out / denom
        num_r = a * z_out + b - c * z_in_med * z_out - d * z_in_med
        r_p = num_r / denom
        t_i = abs(t_p) ** 2 * (z_in_med / z_out) if z_out > 0 else 0.0
        r_i = abs(r_p) ** 2
        t_i = float(np.clip(np.real(t_i), 0.0, 1.0))
        r_i = float(np.clip(np.real(r_i), 0.0, 1.0))
        if t_i + r_i > 1.0:
            scale = 1.0 / (t_i + r_i)
            t_i *= scale
            r_i *= scale
        return t_i, r_i, zin

    def interface_states(
        self,
        f_hz: float,
        p0_pa: float = 1.0,
        layers: list[BowlLayer] | None = None,
    ) -> list[InterfaceState]:
        layers = layers or self.build_layers()
        zin = self.input_impedance(f_hz, layers)
        p = complex(p0_pa)
        v = p / zin if abs(zin) > 1e-30 else 0j
        states = [
            InterfaceState(
                name="drive",
                pressure_pa=p,
                velocity_m_s=v,
                intensity_w_m2=float(0.5 * (p * np.conj(v)).real),
            )
        ]
        vec = np.array([p, v], dtype=complex)
        for layer in layers:
            m = self._layer_matrix(layer, f_hz)
            try:
                vec = np.linalg.solve(m, vec)
            except np.linalg.LinAlgError:
                break
            p_i, v_i = complex(vec[0]), complex(vec[1])
            intens = float(0.5 * (p_i * np.conj(v_i)).real)
            states.append(
                InterfaceState(
                    name=f"after_{layer.name}",
                    pressure_pa=p_i,
                    velocity_m_s=v_i,
                    intensity_w_m2=intens,
                )
            )
        return states

    def energy_partition(self, f_hz: float | None = None) -> EnergyPartition:
        """Partition drive budget into radiated acoustic power vs heat.

        Absolute intensity transmission from PZT (Z~30 MRayl) into tissue
        is naturally small; we therefore map *relative* stack transmission
        onto the manufacturer P_ac budget with a calibration electro-acoustic
        efficiency (typical 0.5–0.8). Air load → zero radiation.
        """
        p = self.params
        f = f_hz if f_hz is not None else p.f0_hz
        layers = self.build_layers()
        t_i, _r_i, _ = self.transmission_reflection(f, layers)
        mats = self._materials()

        # Electrical/acoustic drive budget (manufacturer anchors)
        p_drive = P_AC_MAX_W * max(0.0, min(1.0, p.drive_level))
        p_drive = min(p_drive, I_MAX_W_CM2 * p.era_cm2)
        stack_eff = float(self.cfg.get("defaults", {}).get("stack_efficiency", 0.65))
        # Allow override via params if present
        stack_eff = float(getattr(p, "stack_efficiency", stack_eff))

        if layers[-1].name == "air" or p.load == "air":
            return EnergyPartition(
                p_drive_w=p_drive,
                p_radiated_w=0.0,
                p_glue_loss_w=p_drive * 0.15,
                p_piezo_heat_w=p_drive * 0.80,
                p_ti_loss_w=p_drive * 0.05,
                efficiency=0.0,
            )

        h_glue = p.glue_thickness_m
        h_pzt = p.resolved_piezo_thickness(mats["pzt"].c_m_s)
        h_ti = p.ti_thickness_m
        alpha_glue = mats["glue"].attenuation_np_m_mhz * (f / 1e6)
        alpha_pzt = mats["pzt"].attenuation_np_m_mhz * (f / 1e6)
        alpha_ti = mats["titanium"].attenuation_np_m_mhz * (f / 1e6)
        loss_glue = 1.0 - math.exp(-4.0 * alpha_glue * h_glue)
        loss_pzt = 1.0 - math.exp(-4.0 * alpha_pzt * h_pzt)
        loss_ti = 1.0 - math.exp(-4.0 * alpha_ti * h_ti)
        lam_glue = mats["glue"].c_m_s / f
        # Thick glue → phase/mismatch penalty (calibration model)
        mismatch_extra = min(0.85, (h_glue / max(lam_glue, 1e-9)) * 8.0)

        # Reference transmission: thin glue (1 µm) at same f / Ti / load
        ref_params = BowlParams(**{**p.__dict__})
        ref_params.glue_thickness_m = 1e-6
        ref_bowl = AcousticBowl(ref_params, self.cfg)
        t_ref, _, _ = ref_bowl.transmission_reflection(f)
        t_ref = max(t_ref, 1e-12)
        t_rel = min(1.5, t_i / t_ref)  # relative to thin-glue reference

        # Coupling from relative T and absorption / mismatch
        absorbed = min(0.95, loss_glue + loss_pzt + loss_ti + 0.5 * mismatch_extra)
        coupling = max(0.0, t_rel * (1.0 - absorbed))
        coupling = min(1.0, coupling)

        p_rad = min(P_AC_MAX_W, p_drive * stack_eff * coupling)
        remain = max(0.0, p_drive - p_rad)
        w_glue = 0.20 + mismatch_extra
        w_pzt = 0.70
        w_ti = 0.10
        w_sum = w_glue + w_pzt + w_ti
        eff = p_rad / p_drive if p_drive > 0 else 0.0
        return EnergyPartition(
            p_drive_w=p_drive,
            p_radiated_w=p_rad,
            p_glue_loss_w=remain * (w_glue / w_sum),
            p_piezo_heat_w=remain * (w_pzt / w_sum),
            p_ti_loss_w=remain * (w_ti / w_sum),
            efficiency=eff,
        )

    def spectrum(
        self,
        f_min_hz: float | None = None,
        f_max_hz: float | None = None,
        n: int = 201,
    ) -> list[SpectrumPoint]:
        f0 = self.params.f0_hz
        f_min = f_min_hz if f_min_hz is not None else f0 * 0.85
        f_max = f_max_hz if f_max_hz is not None else f0 * 1.15
        freqs = np.linspace(f_min, f_max, n)
        layers = self.build_layers()
        out: list[SpectrumPoint] = []
        for f in freqs:
            t_i, r_i, zin = self.transmission_reflection(float(f), layers)
            out.append(
                SpectrumPoint(
                    f_hz=float(f),
                    t_intensity=t_i,
                    r_intensity=r_i,
                    z_in_real=float(zin.real),
                    z_in_imag=float(zin.imag),
                    z_in_mag=float(abs(zin)),
                )
            )
        return out

    def find_resonance(self, spectrum: list[SpectrumPoint] | None = None) -> float:
        spec = spectrum if spectrum is not None else self.spectrum()
        if not spec:
            return self.params.f0_hz
        best = max(spec, key=lambda pt: pt.t_intensity)
        if best.t_intensity < 1e-12:
            best = min(spec, key=lambda pt: pt.z_in_mag)
        return best.f_hz

    def sweep_glue(
        self,
        h_min_m: float = 1e-6,
        h_max_m: float = 50e-6,
        n: int = 40,
    ) -> dict[str, Any]:
        original = self.params.glue_thickness_m
        thicknesses = np.linspace(h_min_m, h_max_m, n)
        p_ac, eff, res, t_list = [], [], [], []
        for h in thicknesses:
            self.params.glue_thickness_m = float(h)
            e = self.energy_partition()
            spec = self.spectrum(n=81)
            p_ac.append(e.p_radiated_w)
            eff.append(e.efficiency)
            res.append(self.find_resonance(spec))
            t_list.append(self.transmission_reflection(self.params.f0_hz)[0])
        self.params.glue_thickness_m = original
        return {
            "glue_thickness_um": (thicknesses * 1e6).tolist(),
            "p_ac_w": p_ac,
            "efficiency": eff,
            "resonance_hz": res,
            "t_at_f0": t_list,
        }

    def sweep_titanium(
        self,
        h_min_m: float = 1e-4,
        h_max_m: float = 1e-3,
        n: int = 40,
    ) -> dict[str, Any]:
        original = self.params.ti_thickness_m
        thicknesses = np.linspace(h_min_m, h_max_m, n)
        t_list, res, p_ac, eff = [], [], [], []
        f0 = self.params.f0_hz
        for h in thicknesses:
            self.params.ti_thickness_m = float(h)
            e = self.energy_partition()
            spec = self.spectrum(n=81)
            t_list.append(self.transmission_reflection(f0)[0])
            res.append(self.find_resonance(spec))
            p_ac.append(e.p_radiated_w)
            eff.append(e.efficiency)
        self.params.ti_thickness_m = original
        return {
            "ti_thickness_mm": (thicknesses * 1e3).tolist(),
            "t_at_f0": t_list,
            "resonance_hz": res,
            "p_ac_w": p_ac,
            "efficiency": eff,
            "resonance_shift_hz": [r - f0 for r in res],
        }

    def near_field_map(
        self,
        nx: int = 50,
        nr: int = 40,
        z_max_m: float | None = None,
    ) -> dict[str, Any]:
        p = self.params
        f = p.f0_hz
        a = p.ti_diameter_m / 2.0
        lam = wavelength(f, C_TISSUE)
        zn = (a * a) / lam
        if z_max_m is None:
            z_max_m = max(2.0 * zn, 0.008)
        e = self.energy_partition()
        i0 = e.p_radiated_w / max(p.era_cm2, 1e-9)
        i0 = min(i0, I_MAX_W_CM2)

        z = np.linspace(lam * 0.1, z_max_m, nx)
        r = np.linspace(0.0, a * 1.2, nr)
        zz, rr = np.meshgrid(z, r, indexing="xy")
        s = np.sqrt(zz**2 + a**2) - zz
        on_axis = np.sin(math.pi / lam * s) ** 2
        peak = float(np.max(on_axis)) or 1.0
        on_axis = on_axis / peak
        radial = np.exp(-((rr / a) ** 2))
        x_half = 0.0015 if f > 15e6 else 0.003
        alpha = math.log(2.0) / (2.0 * x_half)
        depth = np.exp(-2.0 * alpha * zz)
        field = i0 * on_axis * radial * depth
        return {
            "z_mm": (z * 1e3).tolist(),
            "r_mm": (r * 1e3).tolist(),
            "i_w_cm2": field.tolist(),
            "z_n_mm": zn * 1e3,
            "lambda_mm": lam * 1e3,
            "i0_w_cm2": i0,
            "a_mm": a * 1e3,
        }

    def schematic_layers(self) -> list[dict[str, Any]]:
        colors = {
            "pzt": "#e6a817",
            "glue": "#c45c26",
            "titanium": "#8a9ba8",
            "gel": "#5dade2",
            "tissue": "#e8a0a0",
            "air": "#d5dbdb",
        }
        out = []
        for layer in self.build_layers():
            h = layer.thickness_m
            if h < 1e-4:
                disp = f"{h * 1e6:.1f} µm"
                scale_group = "um"
            else:
                disp = f"{h * 1e3:.2f} mm"
                scale_group = "mm"
            out.append(
                {
                    "name": layer.name,
                    "material": layer.material.name,
                    "thickness_m": h,
                    "thickness_display": disp,
                    "scale_group": scale_group,
                    "z_mrayl": layer.material.z_mrayl,
                    "c_m_s": layer.material.c_m_s,
                    "diameter_m": layer.diameter_m,
                    "color_hint": colors.get(layer.name, "#888"),
                }
            )
        return out

    def analyze(self) -> BowlResult:
        p = self.params
        f0 = p.f0_hz
        layers = self.build_layers()
        t_i, r_i, zin = self.transmission_reflection(f0, layers)
        spec = self.spectrum(n=121)
        res_hz = self.find_resonance(spec)
        energy = self.energy_partition(f0)
        mats = self._materials()
        h_pzt = p.resolved_piezo_thickness(mats["pzt"].c_m_s)
        area = layers[0].area_m2()
        p0 = math.sqrt(
            max(energy.p_drive_w, 1e-12) * layers[0].material.z_rayl / max(area, 1e-9)
        )
        interfaces = self.interface_states(f0, p0_pa=p0, layers=layers)
        return BowlResult(
            params={
                "f0_hz": p.f0_hz,
                "drive_level": p.drive_level,
                "load": p.load,
                "piezo_material": p.piezo_material,
                "glue_material": p.glue_material,
                "ti_thickness_m": p.ti_thickness_m,
                "ti_diameter_m": p.ti_diameter_m,
                "piezo_diameter_m": p.piezo_diameter_m,
                "glue_thickness_m": p.glue_thickness_m,
                "gel_thickness_m": p.gel_thickness_m,
                "era_cm2": p.era_cm2,
                "piezo_thickness_m": h_pzt,
                "piezo_thickness_suggested_m": suggested_piezo_thickness(
                    f0, mats["pzt"].c_m_s
                ),
                "d_eq_mm": era_equivalent_diameter_m(p.era_cm2) * 1e3,
            },
            f0_hz=f0,
            t_at_f0=t_i,
            r_at_f0=r_i,
            z_in_at_f0=zin,
            resonance_hz=res_hz,
            energy=energy,
            interfaces=interfaces,
            layers_schematic=self.schematic_layers(),
            calibration=p.calibration,
        )

    def to_api_dict(self) -> dict[str, Any]:
        r = self.analyze()
        return {
            "calibration": r.calibration,
            "params": r.params,
            "f0_hz": r.f0_hz,
            "t_at_f0": r.t_at_f0,
            "r_at_f0": r.r_at_f0,
            "z_in_real": float(r.z_in_at_f0.real),
            "z_in_imag": float(r.z_in_at_f0.imag),
            "z_in_mag": float(abs(r.z_in_at_f0)),
            "resonance_hz": r.resonance_hz,
            "resonance_shift_hz": r.resonance_hz - r.f0_hz,
            "energy": asdict(r.energy),
            "interfaces": [
                {
                    "name": i.name,
                    "pressure_pa_abs": float(abs(i.pressure_pa)),
                    "velocity_abs": float(abs(i.velocity_m_s)),
                    "intensity_w_m2": i.intensity_w_m2,
                }
                for i in r.interfaces
            ],
            "layers": r.layers_schematic,
            "anchors": {
                "era_cm2": ERA_CM2,
                "i_max_w_cm2": I_MAX_W_CM2,
                "p_ac_max_w": P_AC_MAX_W,
                "c_tissue": C_TISSUE,
            },
        }


def bowl_params_from_dict(
    data: dict[str, Any], base: BowlParams | None = None
) -> BowlParams:
    src = base or default_bowl_params()
    p = BowlParams(**{f: getattr(src, f) for f in BowlParams.__dataclass_fields__})
    mapping = {
        "f0_hz": float,
        "drive_level": float,
        "load": str,
        "piezo_material": str,
        "glue_material": str,
        "ti_thickness_m": float,
        "ti_diameter_m": float,
        "piezo_thickness_m": lambda x: None if x is None else float(x),
        "piezo_diameter_m": float,
        "glue_thickness_m": float,
        "gel_thickness_m": float,
        "era_cm2": float,
    }
    for key, caster in mapping.items():
        if key in data and data[key] is not None:
            setattr(p, key, caster(data[key]))
    p.piezo_diameter_m = min(p.piezo_diameter_m, p.ti_diameter_m)
    p.glue_thickness_m = float(np.clip(p.glue_thickness_m, 1e-7, 1e-4))
    p.ti_thickness_m = float(np.clip(p.ti_thickness_m, 5e-5, 2e-3))
    p.drive_level = float(np.clip(p.drive_level, 0.0, 1.0))
    if p.f0_hz not in (10e6, 19e6):
        p.f0_hz = 10e6 if p.f0_hz < 14.5e6 else 19e6
    p.calibration = True
    return p
