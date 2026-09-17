"""Multilayer acoustic T-matrix stack: PZT → glue → Ti → gel → skin."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class StackLayer:
    name: str
    z_mrayl: float  # acoustic impedance in MRayl
    thickness_m: float
    c: float  # sound speed m/s


@dataclass
class AcousticStack:
    """Transfer-matrix transmission through layered media."""

    layers: list[StackLayer] = field(default_factory=list)
    stack_efficiency: float = 0.65  # electro-acoustic 0.5–0.8
    gel_thickness_m: float = 0.0003
    gel_present: bool = True

    @classmethod
    def default(cls, piezo_h_m: float = 0.0002) -> AcousticStack:
        return cls(
            layers=[
                StackLayer("pzt", 32.0, piezo_h_m, 4000),
                StackLayer("glue", 2.5, 1e-5, 2000),
                StackLayer("titanium", 27.0, 3e-4, 6100),
            ]
        )

    def with_gel_skin(
        self,
        gel_thickness_m: float,
        gel_present: bool = True,
        z_skin_mrayl: float = 1.62,
    ) -> list[StackLayer]:
        layers = list(self.layers)
        if gel_present and gel_thickness_m > 0:
            layers.append(StackLayer("gel", 1.5, gel_thickness_m, 1480))
            layers.append(StackLayer("skin", z_skin_mrayl, 0.002, 1540))
        else:
            layers.append(StackLayer("air", 0.0004, 0.01, 343))
        return layers

    def transmission_coefficient(
        self,
        f_hz: float,
        gel_thickness_m: float | None = None,
        gel_present: bool | None = None,
    ) -> float:
        """Intensity transmission |T|² via 2×2 T-matrix (normal incidence)."""
        gt = self.gel_thickness_m if gel_thickness_m is None else gel_thickness_m
        gp = self.gel_present if gel_present is None else gel_present

        if not gp or gt <= 0:
            return 0.0  # no acoustic coupling → P_ac ≈ 0

        layers = self.with_gel_skin(gt, True)
        # Build cumulative T-matrix
        # T = [[A, B], [C, D]] relating pressure/velocity
        a, b, c, d = 1.0, 0.0, 0.0, 1.0
        for layer in layers:
            z = layer.z_mrayl * 1e6  # Rayl
            k = 2.0 * math.pi * f_hz / layer.c
            kd = k * layer.thickness_m
            cl, sl = math.cos(kd), math.sin(kd)
            # Layer matrix
            a2 = cl
            b2 = 1j * z * sl
            c2 = 1j * sl / z if z > 0 else 0j
            d2 = cl
            # Multiply
            na = a * a2 + b * c2
            nb = a * b2 + b * d2
            nc = c * a2 + d * c2
            nd = c * b2 + d * d2
            a, b, c, d = na, nb, nc, nd

        z_in = layers[0].z_mrayl * 1e6
        z_out = layers[-1].z_mrayl * 1e6
        # Transmission pressure coefficient (approx)
        denom = a * z_out + b + c * z_in * z_out + d * z_in
        if abs(denom) < 1e-30:
            return 0.0
        t_p = 2.0 * z_out / denom
        # Intensity transmission (real part)
        t_i = abs(t_p) ** 2 * (z_in / z_out) if z_out > 0 else 0.0
        # Clamp and apply stack efficiency
        t_i = max(0.0, min(1.0, t_i.real if isinstance(t_i, complex) else t_i))
        return float(t_i) * self.stack_efficiency

    def acoustic_power(
        self,
        p_elec_at_piezo: float,
        f_hz: float,
        gel_thickness_m: float | None = None,
        gel_present: bool | None = None,
    ) -> float:
        """P_ac from electrical power at piezo through stack."""
        gp = self.gel_present if gel_present is None else gel_present
        if not gp:
            return 0.0
        t = self.transmission_coefficient(f_hz, gel_thickness_m, gp)
        return p_elec_at_piezo * t
