"""Shared frequency policy for therapy sim + acoustic bowl + LDM stub.

Allowed simulation set: {1, 3, 10, 19} MHz.
Manufacturer home-device defaults remain 10 MHz (SKINOVA_10/MED) and 19 MHz (SKINOVA_19).
1/3 MHz are clinical / LDM-class options for simulation — not factory home firmware hops.
"""

from __future__ import annotations

import math
from typing import Any

ALLOWED_F0_HZ: frozenset[float] = frozenset({1e6, 3e6, 10e6, 19e6})
ALLOWED_F0_MHZ: tuple[int, ...] = (1, 3, 10, 19)

# Manufacturer-ish home defaults (immutable product story)
HOME_DEFAULT_F0_HZ: dict[str, float] = {
    "SKINOVA_10": 10e6,
    "SKINOVA_MED": 10e6,
    "SKINOVA_19": 19e6,
}

# Half-value depths [m]: 10/19 from Wellcomet claims; 1/3 physics-scaled (α~f^n, n≈1)
# from 10 MHz @ 3 mm → x½(f) ≈ 3 mm * (10/f_MHz). Documented as CALIBRATION.
HALF_VALUE_DEPTH_M: dict[float, float] = {
    1e6: 0.030,   # ~30 mm — calibration, α∝f from 10 MHz anchor
    3e6: 0.010,   # ~10 mm — calibration
    10e6: 0.003,  # manufacturer claim
    19e6: 0.0015,  # manufacturer claim
}

C_TISSUE = 1540.0
C_PZT_DEFAULT = 4200.0


def nearest_allowed_f0(f_hz: float) -> float:
    """Snap arbitrary Hz to closest allowed frequency."""
    return min(ALLOWED_F0_HZ, key=lambda a: abs(a - f_hz))


def validate_f0(f_hz: float) -> float:
    """Return f_hz if allowed (within 1 Hz), else nearest allowed."""
    for a in ALLOWED_F0_HZ:
        if abs(f_hz - a) < 1.0:
            return a
    return nearest_allowed_f0(f_hz)


def is_allowed_f0(f_hz: float) -> bool:
    return any(abs(f_hz - a) < 1.0 for a in ALLOWED_F0_HZ)


def wavelength_m(f_hz: float, c: float = C_TISSUE) -> float:
    return c / f_hz


def suggested_piezo_thickness_m(f_hz: float, c_pzt: float = C_PZT_DEFAULT) -> float:
    """λ/2 thickness-mode: h = c / (2 f0)."""
    return c_pzt / (2.0 * f_hz)


def half_value_depth_m(f_hz: float, overrides: dict[Any, float] | None = None) -> float:
    """Return x½ for f0; prefer exact key, then override map, then physics scale."""
    f = validate_f0(f_hz)
    if overrides:
        key_str = str(int(f))
        if key_str in overrides:
            return float(overrides[key_str])
        if f in overrides:
            return float(overrides[f])
        if int(f) in overrides:
            return float(overrides[int(f)])
    if f in HALF_VALUE_DEPTH_M:
        return HALF_VALUE_DEPTH_M[f]
    # fallback α∝f from 10 MHz
    return 0.003 * (10e6 / f)


def piezo_thickness_suggestions() -> dict[str, float]:
    return {f"{int(f/1e6)}MHz": suggested_piezo_thickness_m(f) for f in sorted(ALLOWED_F0_HZ)}


def wavelength_suggestions(c: float = C_TISSUE) -> dict[str, float]:
    return {f"{int(f/1e6)}MHz": wavelength_m(f, c) for f in sorted(ALLOWED_F0_HZ)}


def half_value_suggestions() -> dict[str, float]:
    return {f"{int(f/1e6)}MHz": half_value_depth_m(f) for f in sorted(ALLOWED_F0_HZ)}


def frequency_policy_dict() -> dict[str, Any]:
    return {
        "allowed_hz": sorted(ALLOWED_F0_HZ),
        "allowed_mhz": list(ALLOWED_F0_MHZ),
        "home_defaults_hz": dict(HOME_DEFAULT_F0_HZ),
        "half_value_depth_m": {str(int(k)): v for k, v in HALF_VALUE_DEPTH_M.items()},
        "wavelength_m_tissue": wavelength_suggestions(),
        "piezo_lambda_half_m": piezo_thickness_suggestions(),
        "note": (
            "Allowed set {1,3,10,19} MHz for simulation. "
            "Home models default 10/19 MHz; 1/3 MHz are clinical/LDM-class options "
            "(not claiming factory home firmware frequency hops). "
            "x½ for 1/3 MHz is calibration (α∝f scaled from 10 MHz claim)."
        ),
    }
