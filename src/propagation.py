"""1D plane-wave intensity propagation and near-field geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

C_TISSUE = 1540.0  # m/s
RHO_TISSUE = 1050.0  # kg/m³


def alpha_from_half_value(x_half_m: float) -> float:
    """α = ln(2) / (2 * x½)  [Np/m] so that I(x½)=I0/2."""
    return math.log(2.0) / (2.0 * x_half_m)


def half_value_from_alpha(alpha_np_m: float) -> float:
    return math.log(2.0) / (2.0 * alpha_np_m)


def intensity_at_depth(i0: float, alpha_np_m: float, x_m: float) -> float:
    """I(x) = I0 * exp(-2 α x)."""
    return i0 * math.exp(-2.0 * alpha_np_m * x_m)


def wavelength(f_hz: float, c: float = C_TISSUE) -> float:
    return c / f_hz


def near_field_length(era_m2: float, f_hz: float, c: float = C_TISSUE) -> float:
    """z_n = a² / λ for piston radiator, a = sqrt(ERA/π)."""
    a = math.sqrt(era_m2 / math.pi)
    lam = wavelength(f_hz, c)
    return (a * a) / lam


def equivalent_diameter(era_m2: float) -> float:
    return 2.0 * math.sqrt(era_m2 / math.pi)


@dataclass
class PropagationResult:
    x_m: np.ndarray
    i_w_m2: np.ndarray
    alpha_np_m: float
    x_half_m: float
    lambda_m: float
    z_n_m: float
    p_rms_pa: np.ndarray


class Propagation:
    """1D exponential attenuation; optional crude 2D radial map."""

    def __init__(
        self,
        f_hz: float,
        x_half_m: float | None = None,
        era_m2: float = 3.0e-4,
        c: float = C_TISSUE,
        rho: float = RHO_TISSUE,
        enable_2d: bool = False,
    ) -> None:
        self.f_hz = f_hz
        self.era_m2 = era_m2
        self.c = c
        self.rho = rho
        self.enable_2d = enable_2d
        if x_half_m is None:
            # Wellcomet claims
            x_half_m = 0.003 if f_hz < 15e6 else 0.0015
        self.x_half_m = x_half_m
        self.alpha = alpha_from_half_value(x_half_m)

    def profile(
        self,
        i0_w_cm2: float,
        x_max_m: float = 0.008,
        n: int = 80,
    ) -> PropagationResult:
        x = np.linspace(0.0, x_max_m, n)
        i0_si = i0_w_cm2 * 1e4  # W/cm² → W/m²
        i = i0_si * np.exp(-2.0 * self.alpha * x)
        z = self.rho * self.c
        p_rms = np.sqrt(np.maximum(i, 0.0) * z)
        return PropagationResult(
            x_m=x,
            i_w_m2=i,
            alpha_np_m=self.alpha,
            x_half_m=self.x_half_m,
            lambda_m=wavelength(self.f_hz, self.c),
            z_n_m=near_field_length(self.era_m2, self.f_hz, self.c),
            p_rms_pa=p_rms,
        )

    def intensity_w_cm2(self, i0_w_cm2: float, x_m: float) -> float:
        return intensity_at_depth(i0_w_cm2, self.alpha, x_m)

    def map_2d(
        self,
        i0_w_cm2: float,
        x_max_m: float = 0.006,
        r_max_m: float | None = None,
        nx: int = 40,
        nr: int = 30,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Optional lateral Gaussian taper × depth exponential (not full diffraction)."""
        if r_max_m is None:
            r_max_m = equivalent_diameter(self.era_m2) / 2.0
        x = np.linspace(0.0, x_max_m, nx)
        r = np.linspace(0.0, r_max_m, nr)
        xx, rr = np.meshgrid(x, r, indexing="xy")
        a = math.sqrt(self.era_m2 / math.pi)
        radial = np.exp(-(rr / a) ** 2)
        depth = np.exp(-2.0 * self.alpha * xx)
        return x, r, i0_w_cm2 * radial * depth
