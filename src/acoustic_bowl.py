"""Acoustic bowl (чаша) multilayer simulation: piezo → glue → Ti bottom → [match] → load.

Titanium is a half-cup / bowl (полустакан): piezo is glued on the INSIDE bottom;
ultrasound exits the OUTER titanium face toward gel/tissue. Side walls of the cup
are the electrical return path (PCB ↔ Ti), not the primary radiating surface.

1D transfer-matrix along the radiating axis (cup bottom). Cup depth / wall thickness
and electrode series R are CALIBRATION_PRESET — never factory facts.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from src.frequencies import (
    ALLOWED_F0_HZ,
    frequency_policy_dict,
    half_value_depth_m,
    suggested_piezo_thickness_m,
    validate_f0,
    wavelength_m,
)

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

# Re-export helpers used by tests / API
suggested_piezo_thickness = suggested_piezo_thickness_m
wavelength = wavelength_m


def _load_bowl_yaml() -> dict[str, Any]:
    path = CONFIG / "calibration_bowl.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def era_equivalent_diameter_m(era_cm2: float = ERA_CM2) -> float:
    return 2.0 * math.sqrt((era_cm2 * 1e-4) / math.pi)


def diameter_to_era_cm2(diameter_m: float) -> float:
    """Circular ERA (cm²) from radiating diameter (m): π(d/2)² in cm²."""
    return math.pi * (max(diameter_m, 0.0) / 2.0) ** 2 * 1e4


@dataclass
class Material:
    name: str
    rho_kg_m3: float
    c_m_s: float
    z_mrayl: float
    attenuation_np_m_mhz: float = 0.0
    key: str = ""
    kt: float = 0.0

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
    load: str = "gel_tissue"  # air|water|gel|soft_tissue|fat|bone|gel_tissue
    piezo_material: str = "pzt8"
    glue_material: str = "glue_epoxy"
    face_material: str = "titanium"
    ti_thickness_m: float = 3e-4  # Ti bottom (radiating) thickness
    ti_diameter_m: float = 0.01954  # radiating outer face Ø
    # Half-cup geometry (calibration — not factory)
    cup_inner_diameter_m: float = 0.0185
    cup_outer_diameter_m: float = 0.01954
    cup_wall_thickness_m: float = 0.00052
    cup_depth_m: float = 0.004
    piezo_thickness_m: float | None = None
    piezo_diameter_m: float = 0.018
    glue_thickness_m: float = 1e-5
    gel_thickness_m: float = 3e-4
    matching_enabled: bool = False
    matching_material: str = "matching_epoxy"
    matching_thickness_m: float = 5e-5
    backing: str = "air"  # air | heavy
    era_cm2: float = ERA_CM2
    stack_efficiency: float = 0.65
    kt: float = 0.64
    spectrum_span: float = 0.15
    calibration: bool = True
    # Electrode / PCB (series R affect drive efficiency)
    pcb_drive_v: float = 40.0
    p_elec_max_w: float = 8.0  # electrical power budget (Kalibrierung)
    r_wire_piezo_ohm: float = 0.5
    r_ti_return_ohm: float = 0.2
    droplet_demo: bool = False
    # optional material property overrides (calibration)
    piezo_rho: float | None = None
    piezo_c: float | None = None
    piezo_z_mrayl: float | None = None
    face_z_mrayl: float | None = None
    load_z_mrayl: float | None = None

    def resolved_piezo_thickness(self, c_pzt: float) -> float:
        if self.piezo_thickness_m is not None and self.piezo_thickness_m > 0:
            return float(self.piezo_thickness_m)
        return suggested_piezo_thickness_m(self.f0_hz, c_pzt)

    def sync_cup_radiator(self) -> None:
        """Keep radiating Ø linked with cup outer face; derive wall from inner/outer."""
        # Prefer positive values; keep ti_diameter and cup_outer equal (linked).
        if self.ti_diameter_m > 0 and self.cup_outer_diameter_m > 0:
            # Already linked by caller; recompute wall if possible
            pass
        elif self.cup_outer_diameter_m > 0:
            self.ti_diameter_m = float(self.cup_outer_diameter_m)
        elif self.ti_diameter_m > 0:
            self.cup_outer_diameter_m = float(self.ti_diameter_m)
        if self.cup_inner_diameter_m > 0 and self.cup_outer_diameter_m > self.cup_inner_diameter_m:
            self.cup_wall_thickness_m = (
                self.cup_outer_diameter_m - self.cup_inner_diameter_m
            ) / 2.0


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
    z_in_phase_rad: float = 0.0
    t_phase_rad: float = 0.0


@dataclass
class EnergyPartition:
    p_drive_w: float
    p_radiated_w: float
    p_glue_loss_w: float
    p_piezo_heat_w: float
    p_ti_loss_w: float
    efficiency: float
    bandwidth_factor: float = 1.0


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
    time_of_flight_s: float = 0.0
    half_value_m: float = 0.0
    lambda_m: float = 0.0


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
        kt=float(m.get("kt", 0.0)),
    )


def default_bowl_params(cfg: dict[str, Any] | None = None) -> BowlParams:
    cfg = cfg or _load_bowl_yaml()
    d = cfg["defaults"]
    piezo_h = d.get("piezo_thickness_m")
    p = BowlParams(
        f0_hz=validate_f0(float(d["f0_hz"])),
        drive_level=float(d["drive_level"]),
        load=str(d["load"]),
        piezo_material=str(d["piezo_material"]),
        glue_material=str(d["glue_material"]),
        face_material=str(d.get("face_material", "titanium")),
        ti_thickness_m=float(d.get("ti_bottom_thickness_m", d["ti_thickness_m"])),
        ti_diameter_m=float(d.get("cup_outer_diameter_m", d["ti_diameter_m"])),
        cup_inner_diameter_m=float(d.get("cup_inner_diameter_m", 0.0185)),
        cup_outer_diameter_m=float(d.get("cup_outer_diameter_m", d.get("ti_diameter_m", 0.01954))),
        cup_wall_thickness_m=float(d.get("cup_wall_thickness_m", 0.00052)),
        cup_depth_m=float(d.get("cup_depth_m", 0.004)),
        piezo_thickness_m=None if piezo_h is None else float(piezo_h),
        piezo_diameter_m=float(d["piezo_diameter_m"]),
        glue_thickness_m=float(d["glue_thickness_m"]),
        gel_thickness_m=float(d["gel_thickness_m"]),
        matching_enabled=bool(d.get("matching_enabled", False)),
        matching_material=str(d.get("matching_material", "matching_epoxy")),
        matching_thickness_m=float(d.get("matching_thickness_m", 5e-5)),
        backing=str(d.get("backing", "air")),
        era_cm2=float(cfg.get("anchors", {}).get("era_cm2", ERA_CM2)),
        stack_efficiency=float(d.get("stack_efficiency", 0.65)),
        kt=float(d.get("kt", 0.64)),
        spectrum_span=float(d.get("spectrum_span", 0.15)),
        calibration=bool(cfg.get("CALIBRATION_PRESET", True)),
        pcb_drive_v=float(d.get("pcb_drive_v", 40.0)),
        p_elec_max_w=float(d.get("p_elec_max_w", 8.0)),
        r_wire_piezo_ohm=float(d.get("r_wire_piezo_ohm", 0.5)),
        r_ti_return_ohm=float(d.get("r_ti_return_ohm", 0.2)),
        droplet_demo=bool(d.get("droplet_demo", False)),
    )
    p.sync_cup_radiator()
    return p


def _material_groups(mats: dict[str, Any]) -> dict[str, list[str]]:
    piezo = [k for k in mats if k.startswith("pzt") or k in ("batio3", "piezo_custom")]
    glue = [k for k in mats if k.startswith("glue")]
    face = [k for k in mats if k in ("titanium", "titanium_pvd", "stainless", "face_custom")]
    matching = [k for k in mats if k.startswith("matching")]
    backing = [k for k in mats if k.startswith("backing")]
    load = [k for k in mats if k in ("air", "water", "gel", "tissue", "fat", "bone", "load_custom")]
    return {
        "piezo_materials": piezo,
        "glue_materials": glue,
        "face_materials": face,
        "matching_materials": matching,
        "backing_materials": backing,
        "load_materials": load,
    }


def params_help(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or _load_bowl_yaml()
    mats: dict[str, Any] = {}
    for k, m in cfg["materials"].items():
        mats[k] = {
            "name": m["name"],
            "z_mrayl": m["z_mrayl"],
            "c_m_s": m["c_m_s"],
            "rho_kg_m3": m["rho_kg_m3"],
            "kt": m.get("kt", 0.0),
            "help": m.get("help", ""),
        }
    groups = _material_groups(mats)
    policy = frequency_policy_dict()
    return {
        "calibration": bool(cfg.get("CALIBRATION_PRESET", True)),
        "label": cfg.get("label", ""),
        "anchors": cfg.get("anchors", {}),
        "ranges": cfg.get("ranges", {}),
        "materials": mats,
        **groups,
        "presets": list((cfg.get("presets") or {}).keys()),
        "preset_defs": cfg.get("presets", {}),
        "notes": cfg.get("notes", []),
        "suggested_piezo_thickness_m": policy["piezo_lambda_half_m"],
        "wavelength_m": policy["wavelength_m_tissue"],
        "half_value_depth_m": policy["half_value_depth_m"],
        "allowed_f0_hz": policy["allowed_hz"],
        "frequency_policy": policy,
        "d_eq_mm": era_equivalent_diameter_m() * 1e3,
        "loads": ["air", "water", "gel", "soft_tissue", "fat", "bone", "gel_tissue"],
        "backing_options": ["air", "heavy"],
        "geometry_keys": [
            "cup_inner_diameter_m",
            "cup_outer_diameter_m",
            "cup_wall_thickness_m",
            "cup_depth_m",
            "ti_thickness_m",
            "piezo_diameter_m",
            "glue_thickness_m",
        ],
        "electrode_keys": ["pcb_drive_v", "p_elec_max_w", "r_wire_piezo_ohm", "r_ti_return_ohm", "drive_level"],
        "stack_order": ["pzt", "glue", "ti_bottom", "load"],
    }


def apply_named_preset(name: str, base: BowlParams | None = None) -> BowlParams:
    cfg = _load_bowl_yaml()
    presets = cfg.get("presets") or {}
    if name not in presets:
        raise KeyError(f"Unknown bowl preset '{name}'")
    return bowl_params_from_dict(dict(presets[name]), base or default_bowl_params(cfg))


class AcousticBowl:
    """Multilayer transfer-matrix bowl simulator."""

    def __init__(
        self,
        params: BowlParams | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        self.cfg = cfg or _load_bowl_yaml()
        self.params = params or default_bowl_params(self.cfg)

    def _mat(self, key: str) -> Material:
        m = material_from_cfg(key, self.cfg)
        p = self.params
        if key == p.piezo_material or key.startswith("pzt") or key in ("batio3", "piezo_custom"):
            if p.piezo_rho is not None:
                m.rho_kg_m3 = p.piezo_rho
            if p.piezo_c is not None:
                m.c_m_s = p.piezo_c
            if p.piezo_z_mrayl is not None:
                m.z_mrayl = p.piezo_z_mrayl
            if p.kt:
                m.kt = p.kt
        if key in ("titanium", "titanium_pvd", "stainless", "face_custom") and p.face_z_mrayl is not None:
            m.z_mrayl = p.face_z_mrayl
        return m

    def _materials(self) -> dict[str, Material]:
        p = self.params
        face_key = p.face_material if p.face_material in self.cfg["materials"] else "titanium"
        return {
            "pzt": self._mat(p.piezo_material),
            "glue": self._mat(p.glue_material),
            "titanium": self._mat(face_key),
            "gel": self._mat("gel"),
            "water": self._mat("water"),
            "tissue": self._mat("tissue"),
            "fat": self._mat("fat"),
            "bone": self._mat("bone"),
            "air": self._mat("air"),
            "matching": self._mat(p.matching_material),
            "backing": self._mat("backing_heavy" if p.backing == "heavy" else "backing_air"),
        }

    def _load_layers(self, mats: dict[str, Material], dia: float) -> list[BowlLayer]:
        p = self.params
        load = p.load.lower().replace("-", "_")
        gel_h = p.gel_thickness_m
        out: list[BowlLayer] = []
        if load == "air":
            out.append(BowlLayer("air", mats["air"], 0.01, dia))
        elif load == "water":
            out.append(BowlLayer("water", mats["water"], max(gel_h, 0.002), dia))
        elif load == "gel":
            out.append(BowlLayer("gel", mats["gel"], gel_h, dia))
        elif load in ("soft_tissue", "tissue"):
            tissue = mats["tissue"]
            if p.load_z_mrayl is not None:
                tissue = Material(
                    tissue.name, tissue.rho_kg_m3, tissue.c_m_s, p.load_z_mrayl,
                    tissue.attenuation_np_m_mhz, tissue.key, tissue.kt,
                )
            out.append(BowlLayer("tissue", tissue, 0.005, dia))
        elif load == "fat":
            out.append(BowlLayer("fat", mats["fat"], 0.005, dia))
        elif load == "bone":
            out.append(BowlLayer("bone", mats["bone"], 0.003, dia))
        else:  # gel_tissue default
            out.append(BowlLayer("gel", mats["gel"], gel_h, dia))
            out.append(BowlLayer("tissue", mats["tissue"], 0.005, dia))
        return out

    def build_layers(self) -> list[BowlLayer]:
        """Acoustic axis stack: [backing] → piezo → glue → Ti bottom → [match] → load.

        Cup side walls are electrical return only (not in this 1D path).
        """
        p = self.params
        mats = self._materials()
        h_pzt = p.resolved_piezo_thickness(mats["pzt"].c_m_s)
        d_inner = p.cup_inner_diameter_m if p.cup_inner_diameter_m > 0 else p.ti_diameter_m
        d_outer = p.cup_outer_diameter_m if p.cup_outer_diameter_m > 0 else p.ti_diameter_m
        d_piezo = min(p.piezo_diameter_m, d_inner, d_outer)
        layers: list[BowlLayer] = []
        # Optional backing behind piezo (affects bandwidth via energy model; shown in schematic)
        if p.backing == "heavy":
            layers.append(BowlLayer("backing", mats["backing"], 0.002, d_piezo))
        layers.extend(
            [
                BowlLayer("pzt", mats["pzt"], h_pzt, d_piezo),
                BowlLayer("glue", mats["glue"], max(p.glue_thickness_m, 1e-9), d_piezo),
                # Ti bottom of half-cup — primary radiating wall (outer face → load)
                BowlLayer("ti_bottom", mats["titanium"], p.ti_thickness_m, d_outer),
            ]
        )
        if p.matching_enabled:
            layers.append(
                BowlLayer(
                    "matching",
                    mats["matching"],
                    max(p.matching_thickness_m, 1e-9),
                    d_outer,
                )
            )
        layers.extend(self._load_layers(mats, d_outer))
        return layers

    def electrode_efficiency(self) -> float:
        """Simple series contact model: R_wire_piezo + R_ti_return reduce drive efficiency."""
        r_series = max(0.0, self.params.r_wire_piezo_ohm) + max(
            0.0, self.params.r_ti_return_ohm
        )
        # Educational: assume ~50 Ω nominal piezo branch at resonance
        r_nom = 50.0
        return float(r_nom / (r_nom + r_series))

    def geometry_meta(self) -> dict[str, Any]:
        p = self.params
        return {
            "cup_inner_diameter_m": p.cup_inner_diameter_m,
            "cup_outer_diameter_m": p.cup_outer_diameter_m,
            "cup_wall_thickness_m": p.cup_wall_thickness_m,
            "cup_depth_m": p.cup_depth_m,
            "ti_bottom_thickness_m": p.ti_thickness_m,
            "piezo_diameter_m": p.piezo_diameter_m,
            "glue_thickness_m": p.glue_thickness_m,
            "pcb_drive_v": p.pcb_drive_v,
            "p_elec_max_w": p.p_elec_max_w,
            "r_wire_piezo_ohm": p.r_wire_piezo_ohm,
            "r_ti_return_ohm": p.r_ti_return_ohm,
            "droplet_demo": p.droplet_demo,
            "load": p.load,
            "drive_level": p.drive_level,
            "stack_order": [
                ly.name for ly in self.build_layers() if ly.name != "backing"
            ],
            "note": (
                "1D axis: piezo→glue→Ti bottom→load; side walls = Ti return electrode"
            ),
        }

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

        # First solid radiator layer (skip optional backing for Z_in medium)
        z_in_med = layers[0].material.z_rayl
        for ly in layers:
            if ly.name == "pzt":
                z_in_med = ly.material.z_rayl
                break
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

    def transmission_complex(
        self, f_hz: float, layers: list[BowlLayer] | None = None
    ) -> complex:
        layers = layers or self.build_layers()
        if layers[-1].name == "air" or layers[-1].material.z_mrayl < 0.01:
            return 0j
        z_in_med = layers[0].material.z_rayl
        for ly in layers:
            if ly.name == "pzt":
                z_in_med = ly.material.z_rayl
                break
        z_out = layers[-1].material.z_rayl
        t = self.transfer_matrix(f_hz, layers)
        a, b = t[0, 0], t[0, 1]
        c, d = t[1, 0], t[1, 1]
        denom = a * z_out + b + c * z_in_med * z_out + d * z_in_med
        if abs(denom) < 1e-30:
            return 0j
        return 2.0 * z_out / denom

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

    def _bandwidth_factor(self) -> float:
        """Heavy backing lowers Q → broader band; air-backed → narrower (educational)."""
        if self.params.backing == "heavy":
            return 1.35
        return 0.85

    def energy_partition(self, f_hz: float | None = None) -> EnergyPartition:
        """Partition drive budget into radiated acoustic power vs heat."""
        p = self.params
        f = f_hz if f_hz is not None else p.f0_hz
        layers = self.build_layers()
        t_i, _r_i, _ = self.transmission_reflection(f, layers)
        mats = self._materials()
        bw = self._bandwidth_factor()

        level = max(0.0, min(1.0, p.drive_level))
        # PCB peak voltage scales available drive (~V^2); 40 V = nominal
        v_nom = 40.0
        v_scale = (max(1.0, float(p.pcb_drive_v)) / v_nom) ** 2
        p_drive = P_AC_MAX_W * level * v_scale
        p_drive = min(p_drive, I_MAX_W_CM2 * p.era_cm2)
        p_budget = float(getattr(p, "p_elec_max_w", 8.0) or 8.0)
        if p_budget > 0:
            p_drive = min(p_drive, p_budget)
        stack_eff = float(getattr(p, "stack_efficiency", 0.65))

        if layers[-1].name == "air" or p.load == "air":
            return EnergyPartition(
                p_drive_w=p_drive,
                p_radiated_w=0.0,
                p_glue_loss_w=p_drive * 0.15,
                p_piezo_heat_w=p_drive * 0.80,
                p_ti_loss_w=p_drive * 0.05,
                efficiency=0.0,
                bandwidth_factor=bw,
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
        mismatch_extra = min(0.85, (h_glue / max(lam_glue, 1e-9)) * 8.0)

        ref_params = BowlParams(**{f.name: getattr(p, f.name) for f in fields(p)})
        ref_params.glue_thickness_m = 1e-6
        ref_bowl = AcousticBowl(ref_params, self.cfg)
        t_ref, _, _ = ref_bowl.transmission_reflection(f)
        t_ref = max(t_ref, 1e-12)
        t_rel = min(1.5, t_i / t_ref)

        absorbed = min(0.95, loss_glue + loss_pzt + loss_ti + 0.5 * mismatch_extra)
        # Heavy backing absorbs some drive energy (broader BW trade-off)
        if p.backing == "heavy":
            absorbed = min(0.98, absorbed + 0.08)
        coupling = max(0.0, t_rel * (1.0 - absorbed))
        coupling = min(1.0, coupling)

        # Area scaling: smaller piezo → less radiated power
        area_ratio = (math.pi * (min(p.piezo_diameter_m, p.ti_diameter_m) / 2) ** 2) / ERA_M2
        area_ratio = float(np.clip(area_ratio, 0.2, 1.2))

        elec_eff = self.electrode_efficiency()
        p_rad = min(P_AC_MAX_W, p_drive * stack_eff * coupling * area_ratio * elec_eff)
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
            bandwidth_factor=bw,
        )

    def spectrum(
        self,
        f_min_hz: float | None = None,
        f_max_hz: float | None = None,
        n: int = 201,
    ) -> list[SpectrumPoint]:
        f0 = self.params.f0_hz
        span = float(np.clip(self.params.spectrum_span, 0.05, 0.5))
        f_min = f_min_hz if f_min_hz is not None else f0 * (1.0 - span)
        f_max = f_max_hz if f_max_hz is not None else f0 * (1.0 + span)
        freqs = np.linspace(f_min, f_max, n)
        layers = self.build_layers()
        out: list[SpectrumPoint] = []
        for f in freqs:
            t_i, r_i, zin = self.transmission_reflection(float(f), layers)
            t_c = self.transmission_complex(float(f), layers)
            out.append(
                SpectrumPoint(
                    f_hz=float(f),
                    t_intensity=t_i,
                    r_intensity=r_i,
                    z_in_real=float(zin.real),
                    z_in_imag=float(zin.imag),
                    z_in_mag=float(abs(zin)),
                    z_in_phase_rad=float(np.angle(zin)),
                    t_phase_rad=float(np.angle(t_c)),
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

    def sweep_piezo_diameter(
        self,
        d_min_m: float = 0.010,
        d_max_m: float | None = None,
        n: int = 24,
    ) -> dict[str, Any]:
        d_max = d_max_m if d_max_m is not None else self.params.ti_diameter_m
        original = self.params.piezo_diameter_m
        diams = np.linspace(d_min_m, min(d_max, self.params.ti_diameter_m), n)
        p_ac, intensity, eff = [], [], []
        for d in diams:
            self.params.piezo_diameter_m = float(d)
            e = self.energy_partition()
            area_cm2 = math.pi * (d / 2) ** 2 * 1e4
            p_ac.append(e.p_radiated_w)
            intensity.append(e.p_radiated_w / max(area_cm2, 1e-9))
            eff.append(e.efficiency)
        self.params.piezo_diameter_m = original
        return {
            "piezo_diameter_mm": (diams * 1e3).tolist(),
            "p_ac_w": p_ac,
            "i_sata_w_cm2": [min(i, I_MAX_W_CM2) for i in intensity],
            "efficiency": eff,
        }

    def compare_frequencies(
        self, freqs: list[float] | None = None
    ) -> dict[str, Any]:
        freqs = freqs or sorted(ALLOWED_F0_HZ)
        original_f = self.params.f0_hz
        original_h = self.params.piezo_thickness_m
        rows = []
        for f in freqs:
            f = validate_f0(float(f))
            self.params.f0_hz = f
            # auto λ/2 for fair geometry compare unless user locked thickness
            self.params.piezo_thickness_m = None
            e = self.energy_partition()
            t_i, r_i, zin = self.transmission_reflection(f)
            mats = self._materials()
            h = self.params.resolved_piezo_thickness(mats["pzt"].c_m_s)
            rows.append(
                {
                    "f0_hz": f,
                    "f0_mhz": f / 1e6,
                    "t_at_f0": t_i,
                    "r_at_f0": r_i,
                    "p_ac_w": e.p_radiated_w,
                    "efficiency": e.efficiency,
                    "lambda_mm": wavelength_m(f) * 1e3,
                    "piezo_h_um": h * 1e6,
                    "x_half_mm": half_value_depth_m(f) * 1e3,
                    "z_in_mag": float(abs(zin)),
                }
            )
        self.params.f0_hz = original_f
        self.params.piezo_thickness_m = original_h
        return {"calibration": True, "rows": rows, "fixed_geometry_note": "piezo auto λ/2 per f0"}

    def time_of_flight(self) -> dict[str, Any]:
        layers = self.build_layers()
        parts = []
        total = 0.0
        for ly in layers:
            dt = ly.thickness_m / max(ly.material.c_m_s, 1.0)
            parts.append(
                {
                    "name": ly.name,
                    "thickness_m": ly.thickness_m,
                    "c_m_s": ly.material.c_m_s,
                    "delay_s": dt,
                    "delay_ns": dt * 1e9,
                }
            )
            total += dt
        return {
            "layers": parts,
            "total_s": total,
            "total_ns": total * 1e9,
            "round_trip_ns": total * 2e9,
        }

    def depth_profile(self, n_per_layer: int = 24) -> dict[str, Any]:
        """1D |p| vs depth through stack (standing-wave educational profile)."""
        f = self.params.f0_hz
        layers = self.build_layers()
        e = self.energy_partition()
        area = layers[0].area_m2() if layers else ERA_M2
        p0 = math.sqrt(
            max(e.p_drive_w, 1e-12) * layers[0].material.z_rayl / max(area, 1e-9)
        )
        zin = self.input_impedance(f, layers)
        p = complex(p0)
        v = p / zin if abs(zin) > 1e-30 else 0j
        z_pos = 0.0
        z_mm: list[float] = []
        p_abs: list[float] = []
        i_vals: list[float] = []
        layer_bounds: list[dict[str, Any]] = []
        for layer in layers:
            m = self._layer_matrix(layer, f)
            # sample within layer by subdividing thickness
            n = max(4, n_per_layer)
            z0 = z_pos
            for i in range(n + 1):
                frac = i / n
                # propagate fraction of layer
                h = layer.thickness_m * frac
                sub = BowlLayer(layer.name, layer.material, h, layer.diameter_m)
                try:
                    vec = np.linalg.solve(self._layer_matrix(sub, f), np.array([p, v], dtype=complex))
                except np.linalg.LinAlgError:
                    break
                z_mm.append((z_pos + h) * 1e3)
                p_abs.append(float(abs(vec[0])))
                i_vals.append(float(0.5 * (vec[0] * np.conj(vec[1])).real))
            try:
                vec_end = np.linalg.solve(m, np.array([p, v], dtype=complex))
                p, v = complex(vec_end[0]), complex(vec_end[1])
            except np.linalg.LinAlgError:
                break
            z_pos += layer.thickness_m
            layer_bounds.append(
                {
                    "name": layer.name,
                    "z0_mm": z0 * 1e3,
                    "z1_mm": z_pos * 1e3,
                    "color_hint": {
                        "backing": "#555",
                        "pzt": "#e6a817",
                        "glue": "#c45c26",
                        "ti_bottom": "#8a9ba8",
                        "face": "#8a9ba8",
                        "titanium": "#8a9ba8",
                        "matching": "#9b59b6",
                        "gel": "#5dade2",
                        "tissue": "#e8a0a0",
                        "water": "#3498db",
                        "fat": "#f5cba7",
                        "bone": "#d5d8dc",
                        "air": "#d5dbdb",
                    }.get(layer.name, "#888"),
                }
            )
        return {
            "z_mm": z_mm,
            "pressure_abs": p_abs,
            "intensity_w_m2": i_vals,
            "layers": layer_bounds,
            "f0_hz": f,
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
        lam = wavelength_m(f, C_TISSUE)
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
        x_half = half_value_depth_m(f)
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
            "x_half_mm": x_half * 1e3,
        }

    def schematic_layers(self) -> list[dict[str, Any]]:
        colors = {
            "backing": "#555555",
            "pzt": "#e6a817",
            "glue": "#c45c26",
            "ti_bottom": "#8a9ba8",
            "face": "#8a9ba8",
            "titanium": "#8a9ba8",
            "matching": "#9b59b6",
            "gel": "#5dade2",
            "tissue": "#e8a0a0",
            "water": "#3498db",
            "fat": "#f5cba7",
            "bone": "#d5d8dc",
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
        area = next((ly.area_m2() for ly in layers if ly.name == "pzt"), ERA_M2)
        z_pzt = mats["pzt"].z_rayl
        p0 = math.sqrt(max(energy.p_drive_w, 1e-12) * z_pzt / max(area, 1e-9))
        interfaces = self.interface_states(f0, p0_pa=p0, layers=layers)
        tof = self.time_of_flight()
        return BowlResult(
            params={
                "f0_hz": p.f0_hz,
                "drive_level": p.drive_level,
                "load": p.load,
                "piezo_material": p.piezo_material,
                "glue_material": p.glue_material,
                "face_material": p.face_material,
                "ti_thickness_m": p.ti_thickness_m,
                "ti_bottom_thickness_m": p.ti_thickness_m,
                "ti_diameter_m": p.ti_diameter_m,
                "cup_inner_diameter_m": p.cup_inner_diameter_m,
                "cup_outer_diameter_m": p.cup_outer_diameter_m,
                "cup_wall_thickness_m": p.cup_wall_thickness_m,
                "cup_depth_m": p.cup_depth_m,
                "piezo_diameter_m": p.piezo_diameter_m,
                "glue_thickness_m": p.glue_thickness_m,
                "gel_thickness_m": p.gel_thickness_m,
                "matching_enabled": p.matching_enabled,
                "matching_material": p.matching_material,
                "matching_thickness_m": p.matching_thickness_m,
                "backing": p.backing,
                "era_cm2": p.era_cm2,
                "kt": p.kt,
                "spectrum_span": p.spectrum_span,
                "stack_efficiency": p.stack_efficiency,
                "pcb_drive_v": p.pcb_drive_v,
                "p_elec_max_w": p.p_elec_max_w,
                "r_wire_piezo_ohm": p.r_wire_piezo_ohm,
                "r_ti_return_ohm": p.r_ti_return_ohm,
                "droplet_demo": p.droplet_demo,
                "electrode_efficiency": self.electrode_efficiency(),
                "piezo_thickness_m": h_pzt,
                "piezo_thickness_suggested_m": suggested_piezo_thickness_m(
                    f0, mats["pzt"].c_m_s
                ),
                "d_eq_mm": era_equivalent_diameter_m(p.era_cm2) * 1e3,
                "lambda_m": wavelength_m(f0),
                "x_half_m": half_value_depth_m(f0),
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
            time_of_flight_s=tof["total_s"],
            half_value_m=half_value_depth_m(f0),
            lambda_m=wavelength_m(f0),
        )

    def to_api_dict(self) -> dict[str, Any]:
        r = self.analyze()
        tof = self.time_of_flight()
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
            "time_of_flight": tof,
            "lambda_m": r.lambda_m,
            "x_half_m": r.half_value_m,
            "geometry": self.geometry_meta(),
            "anchors": {
                "era_cm2": ERA_CM2,
                "i_max_w_cm2": I_MAX_W_CM2,
                "p_ac_max_w": P_AC_MAX_W,
                "c_tissue": C_TISSUE,
                "allowed_f0_hz": sorted(ALLOWED_F0_HZ),
            },
        }


def bowl_params_from_dict(
    data: dict[str, Any], base: BowlParams | None = None
) -> BowlParams:
    src = base or default_bowl_params()
    p = BowlParams(**{f.name: getattr(src, f.name) for f in fields(BowlParams)})
    mapping: dict[str, Any] = {
        "f0_hz": float,
        "drive_level": float,
        "load": str,
        "piezo_material": str,
        "glue_material": str,
        "face_material": str,
        "ti_thickness_m": float,
        "ti_bottom_thickness_m": float,  # alias → applied below
        "ti_diameter_m": float,
        "cup_inner_diameter_m": float,
        "cup_outer_diameter_m": float,
        "cup_wall_thickness_m": float,
        "cup_depth_m": float,
        "piezo_thickness_m": lambda x: None if x is None else float(x),
        "piezo_diameter_m": float,
        "glue_thickness_m": float,
        "gel_thickness_m": float,
        "matching_enabled": bool,
        "matching_material": str,
        "matching_thickness_m": float,
        "backing": str,
        "era_cm2": float,
        "stack_efficiency": float,
        "kt": float,
        "spectrum_span": float,
        "pcb_drive_v": float,
        "p_elec_max_w": float,
        "r_wire_piezo_ohm": float,
        "r_ti_return_ohm": float,
        "droplet_demo": bool,
        "piezo_rho": lambda x: None if x is None else float(x),
        "piezo_c": lambda x: None if x is None else float(x),
        "piezo_z_mrayl": lambda x: None if x is None else float(x),
        "face_z_mrayl": lambda x: None if x is None else float(x),
        "load_z_mrayl": lambda x: None if x is None else float(x),
    }
    for key, caster in mapping.items():
        if key in data and data[key] is not None:
            if key == "ti_bottom_thickness_m":
                p.ti_thickness_m = float(data[key])
            else:
                setattr(p, key, caster(data[key]))

    has_ti = "ti_diameter_m" in data and data["ti_diameter_m"] is not None
    has_outer = "cup_outer_diameter_m" in data and data["cup_outer_diameter_m"] is not None
    has_era = "era_cm2" in data and data["era_cm2"] is not None

    # Link radiating Ø ↔ cup outer (editable calibration; manufacturer ERA is only default)
    if has_ti:
        p.cup_outer_diameter_m = float(p.ti_diameter_m)
    elif has_outer:
        p.ti_diameter_m = float(p.cup_outer_diameter_m)
    elif has_era:
        # ERA alone drives equivalent diameter
        p.ti_diameter_m = era_equivalent_diameter_m(float(p.era_cm2))
        p.cup_outer_diameter_m = float(p.ti_diameter_m)

    p.ti_diameter_m = float(np.clip(p.ti_diameter_m, 1e-2, 3e-2))
    p.cup_outer_diameter_m = float(p.ti_diameter_m)
    p.cup_depth_m = float(np.clip(p.cup_depth_m, 5e-4, 2e-2))
    p.cup_inner_diameter_m = float(np.clip(p.cup_inner_diameter_m, 8e-3, 3e-2))

    # If user shrinks radiating/outer Ø below inner, shrink inner (do not inflate outer)
    if p.cup_inner_diameter_m >= p.cup_outer_diameter_m:
        wall = max(min(p.cup_wall_thickness_m, p.cup_outer_diameter_m * 0.08), 1e-4)
        p.cup_inner_diameter_m = max(8e-3, p.cup_outer_diameter_m - 2.0 * wall)
        if p.cup_inner_diameter_m >= p.cup_outer_diameter_m:
            p.cup_inner_diameter_m = p.cup_outer_diameter_m * 0.92
    p.cup_wall_thickness_m = (
        p.cup_outer_diameter_m - p.cup_inner_diameter_m
    ) / 2.0

    # Diameter ↔ ERA: diameter wins when diameter fields present; else ERA drives diameter
    if has_era and not (has_ti or has_outer):
        p.era_cm2 = float(np.clip(p.era_cm2, 0.5, 10.0))
        p.ti_diameter_m = float(np.clip(era_equivalent_diameter_m(p.era_cm2), 1e-2, 3e-2))
        p.cup_outer_diameter_m = float(p.ti_diameter_m)
        if p.cup_inner_diameter_m >= p.cup_outer_diameter_m:
            p.cup_inner_diameter_m = p.cup_outer_diameter_m * 0.92
            p.cup_wall_thickness_m = (
                p.cup_outer_diameter_m - p.cup_inner_diameter_m
            ) / 2.0
    else:
        p.era_cm2 = float(np.clip(diameter_to_era_cm2(p.ti_diameter_m), 0.5, 10.0))

    p.piezo_diameter_m = min(p.piezo_diameter_m, p.cup_inner_diameter_m, p.ti_diameter_m)
    p.glue_thickness_m = float(np.clip(p.glue_thickness_m, 1e-7, 1e-4))
    p.ti_thickness_m = float(np.clip(p.ti_thickness_m, 5e-5, 2e-3))
    p.sync_cup_radiator()
    p.drive_level = float(np.clip(p.drive_level, 0.0, 1.0))
    p.matching_thickness_m = float(np.clip(p.matching_thickness_m, 1e-6, 5e-4))
    p.spectrum_span = float(np.clip(p.spectrum_span, 0.05, 0.5))
    p.pcb_drive_v = float(np.clip(p.pcb_drive_v, 1.0, 100.0))
    p.p_elec_max_w = float(np.clip(p.p_elec_max_w, 0.5, 50.0))
    p.r_wire_piezo_ohm = float(np.clip(p.r_wire_piezo_ohm, 0.0, 50.0))
    p.r_ti_return_ohm = float(np.clip(p.r_ti_return_ohm, 0.0, 50.0))
    p.stack_efficiency = float(np.clip(p.stack_efficiency, 0.1, 1.0))
    p.f0_hz = validate_f0(p.f0_hz)
    if p.backing not in ("air", "heavy"):
        p.backing = "air"
    p.calibration = True
    return p


def compare_bowl_presets(
    a: dict[str, Any], b: dict[str, Any]
) -> dict[str, Any]:
    """Side-by-side A/B compare of two param dicts → metrics + deltas."""
    pa = bowl_params_from_dict(a)
    pb = bowl_params_from_dict(b)
    ra = AcousticBowl(pa).to_api_dict()
    rb = AcousticBowl(pb).to_api_dict()
    keys = ["t_at_f0", "r_at_f0", "resonance_hz", "z_in_mag", "lambda_m", "x_half_m"]
    delta = {k: float(rb.get(k, 0) or 0) - float(ra.get(k, 0) or 0) for k in keys}
    ea, eb = ra["energy"], rb["energy"]
    for ek in ("p_radiated_w", "efficiency", "p_glue_loss_w", "p_piezo_heat_w", "p_ti_loss_w"):
        delta[ek] = float(eb.get(ek, 0)) - float(ea.get(ek, 0))
    return {
        "calibration": True,
        "a": {"params": ra["params"], "metrics": {k: ra.get(k) for k in keys}, "energy": ea},
        "b": {"params": rb["params"], "metrics": {k: rb.get(k) for k in keys}, "energy": eb},
        "delta": delta,
    }
