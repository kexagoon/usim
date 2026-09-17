"""OPTIONAL stub: LDM Triple clinical multi-MHz hopping.

SEPARATE from home Skinova devices. Home devices are monofrequency + burst only.
Do NOT enable this module for SKINOVA_10 / SKINOVA_19 / SKINOVA_MED by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.frequencies import ALLOWED_F0_HZ, validate_f0


@dataclass
class LDMWave:
    """Clinical LDM switching — NOT used by home Skinova handpieces."""

    pair: tuple[float, ...] = (1e6, 3e6, 10e6)
    # Optional extended clinical set including 19 MHz for simulation compare
    pair_extended: tuple[float, ...] = (1e6, 3e6, 10e6, 19e6)
    f_switch_hz: float = 500.0
    enabled: bool = False  # must stay False for home models
    use_extended: bool = False

    def slot_frequencies(self) -> tuple[float, ...]:
        if not self.enabled:
            raise RuntimeError(
                "LDM_TRIPLE is disabled for home Skinova; enable only for clinical PRO simulation"
            )
        slots = self.pair_extended if self.use_extended else self.pair
        return tuple(validate_f0(f) for f in slots)

    def allowed_set(self) -> frozenset[float]:
        return ALLOWED_F0_HZ

    def describe(self) -> str:
        return (
            "LDM® Local Dynamic Micromassage stub — clinical Triple 1/3/10 MHz "
            "(optional +19 MHz). Home Skinova = monofrequency only; "
            "1/3 MHz in the therapy UI are clinical/LDM-class simulation options, "
            "not factory home firmware hops."
        )
