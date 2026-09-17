"""Butterworth–Van Dyke (BVD) piezo model near resonance."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


Z_AIR = 400.0  # Rayl
Z_GEL = 1.5e6  # Rayl ≈ 1.5 MRayl
Z_TISSUE = 1.62e6


@dataclass
class BVDParams:
    """BVD parameters; fs locked to device f0."""

    f0_hz: float
    c0_f: float = 1.5e-9  # F
    k_eff2: float = 0.4
    q_m_air: float = 120.0
    q_m_gel: float = 25.0
    era_m2: float = 3.0e-4

    def __post_init__(self) -> None:
        # C1 from k_eff² = C1/(C0+C1)
        # ⇒ C1 = k²/(1-k²) * C0
        k2 = self.k_eff2
        self.c1_f: float = (k2 / (1.0 - k2)) * self.c0_f
        omega = 2.0 * math.pi * self.f0_hz
        self.l1_h: float = 1.0 / (omega * omega * self.c1_f)
        # Mechanical resistance at air (high Q)
        self.r_m: float = omega * self.l1_h / self.q_m_air


@dataclass
class BVDState:
    r1: float
    fs_hz: float
    fp_hz: float
    q_eff: float
    contact: bool
    z_load: float


def radiation_resistance(z_load: float, era_m2: float, f0_hz: float) -> float:
    """Approximate acoustic radiation contribution referred to electrical port.

    R_rad ∝ (Z_load / Z_ref) scaled so gel load drops Q to q_m_gel range.
    """
    # Reference: full gel load ⇒ R_rad ≈ R_m * (Q_air/Q_gel - 1)
    return max(0.0, z_load / Z_GEL) * era_m2 * 1e-3 * (f0_hz / 10e6)


@dataclass
class PiezoBVD:
    params: BVDParams = field(default_factory=lambda: BVDParams(f0_hz=10e6))
    gel_present: bool = True
    gel_fraction: float = 1.0  # 0=air, 1=full gel contact

    def z_load(self) -> float:
        if not self.gel_present or self.gel_fraction <= 0.0:
            return Z_AIR
        # Blend air ↔ gel/tissue by contact fraction
        g = min(1.0, max(0.0, self.gel_fraction))
        return Z_AIR * (1.0 - g) + Z_GEL * g

    def r1(self) -> float:
        z = self.z_load()
        # Scale R_rad so Q_eff ≈ q_m_gel under full gel
        r_m = self.params.r_m
        if z <= Z_AIR * 2:
            return r_m  # air: almost open circuit radiation
        # Under gel: lower Q
        omega = 2.0 * math.pi * self.params.f0_hz
        r_target = omega * self.params.l1_h / self.params.q_m_gel
        blend = min(1.0, (z - Z_AIR) / (Z_GEL - Z_AIR))
        return r_m + blend * (r_target - r_m)

    def evaluate(self) -> BVDState:
        r1 = self.r1()
        c0 = self.params.c0_f
        c1 = self.params.c1_f
        fs = self.params.f0_hz
        fp = fs * math.sqrt(1.0 + c1 / c0)
        omega = 2.0 * math.pi * fs
        q_eff = omega * self.params.l1_h / max(r1, 1e-12)
        z = self.z_load()
        contact = z > Z_AIR * 10 and self.gel_present and self.gel_fraction > 0.05
        return BVDState(
            r1=r1,
            fs_hz=fs,
            fp_hz=fp,
            q_eff=q_eff,
            contact=contact,
            z_load=z,
        )

    def impedance_at(self, f_hz: float) -> complex:
        """Series-motional branch || C0."""
        w = 2.0 * math.pi * f_hz
        r1 = self.r1()
        zm = r1 + 1j * (w * self.params.l1_h - 1.0 / (w * self.params.c1_f))
        zc0 = 1.0 / (1j * w * self.params.c0_f)
        return 1.0 / (1.0 / zm + 1.0 / zc0)
