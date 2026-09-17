"""1D Pennes bioheat equation + dose integral."""

from __future__ import annotations

import math

from dataclasses import dataclass, field

import numpy as np


@dataclass
class BioheatParams:
    rho: float = 1050.0
    c_heat: float = 3400.0
    k_thermal: float = 0.40
    alpha_np_m: float = 115.0
    wb: float = 0.0005  # blood perfusion 1/s
    rho_b: float = 1050.0
    c_b: float = 3617.0
    t_b_c: float = 37.0
    q_met: float = 500.0
    t_amb_c: float = 34.0  # skin surface ambient


@dataclass
class BioheatState:
    x_m: np.ndarray
    t_c: np.ndarray
    dose_j_m3: np.ndarray


class Bioheat1D:
    """Explicit 1D Pennes on a depth grid; macro dt 1–10 ms."""

    def __init__(
        self,
        params: BioheatParams | None = None,
        x_max_m: float = 0.006,
        n: int = 40,
        t0_c: float = 34.0,
    ) -> None:
        self.params = params or BioheatParams()
        self.x = np.linspace(0.0, x_max_m, n)
        self.dx = float(self.x[1] - self.x[0]) if n > 1 else x_max_m
        self.t = np.full(n, t0_c, dtype=float)
        self.dose = np.zeros(n, dtype=float)

    def reset(self, t0_c: float = 34.0) -> None:
        self.t[:] = t0_c
        self.dose[:] = 0.0

    def step(self, i0_w_cm2: float, dt_s: float, moving: bool = True) -> BioheatState:
        """Advance temperature and dose by one macro step.

        I(x) in W/m²; heat source Q = 2 α I.
        Motion spreads heat → effective derate of surface source.
        Large dt uses internal substeps for explicit stability.
        """
        p = self.params
        i0 = i0_w_cm2 * 1e4  # W/m²
        if moving:
            i0 *= 0.7
        i_x = i0 * np.exp(-2.0 * p.alpha_np_m * self.x)
        q_us = 2.0 * p.alpha_np_m * i_x  # W/m³

        # Explicit Fourier limit: Fo < ~0.4
        dt_max = 0.4 * p.rho * p.c_heat * (self.dx**2) / max(p.k_thermal, 1e-12)
        n_sub = max(1, int(math.ceil(dt_s / max(dt_max, 1e-9))))
        dt_sub = dt_s / n_sub

        for _ in range(n_sub):
            t = self.t
            d2 = np.zeros_like(t)
            d2[1:-1] = (t[2:] - 2 * t[1:-1] + t[:-2]) / (self.dx**2)
            d2[0] = (t[1] - t[0]) / (self.dx**2)
            d2[-1] = (t[-2] - t[-1]) / (self.dx**2)

            perfusion = p.rho_b * p.c_b * p.wb * (p.t_b_c - t)
            dT = (p.k_thermal * d2 + q_us + perfusion + p.q_met) / (p.rho * p.c_heat)
            dT[0] -= (t[0] - p.t_amb_c) * 0.05
            self.t = t + dT * dt_sub

        self.dose += q_us * dt_s
        return BioheatState(x_m=self.x.copy(), t_c=self.t.copy(), dose_j_m3=self.dose.copy())


@dataclass
class PiezoThermalRC:
    """Lumped RC thermal model of piezo + titanium face."""

    c_th: float = 8.0  # J/K
    r_th: float = 12.0  # K/W to ambient
    h_gel: float = 0.8  # W/K coupling to skin when gel present
    t_amb_c: float = 25.0
    t_c: float = 25.0

    def step(
        self,
        p_piezo_loss_w: float,
        dt_s: float,
        t_skin_c: float = 34.0,
        gel_present: bool = True,
    ) -> float:
        h = self.h_gel if gel_present else 0.0
        dT = (
            p_piezo_loss_w
            - (self.t_c - self.t_amb_c) / self.r_th
            - h * (self.t_c - t_skin_c)
        ) / self.c_th
        self.t_c += dT * dt_s
        return self.t_c

    def reset(self, t_c: float | None = None) -> None:
        self.t_c = self.t_amb_c if t_c is None else t_c
