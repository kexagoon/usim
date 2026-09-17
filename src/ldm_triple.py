"""OPTIONAL stub: LDM Triple clinical multi-MHz hopping.

SEPARATE from home Skinova devices. Home devices are monofrequency + burst only.
Do NOT enable this module for SKINOVA_10 / SKINOVA_19 / SKINOVA_MED by default.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LDMWave:
    """Clinical LDM switching — NOT used by home Skinova handpieces."""

    pair: tuple[float, ...] = (1e6, 3e6, 10e6)
    f_switch_hz: float = 500.0
    enabled: bool = False  # must stay False for home models

    def slot_frequencies(self) -> tuple[float, ...]:
        if not self.enabled:
            raise RuntimeError(
                "LDM_TRIPLE is disabled for home Skinova; enable only for clinical PRO simulation"
            )
        return self.pair

    def describe(self) -> str:
        return (
            "LDM® Local Dynamic Micromassage stub — clinical Triple 1/3/10 MHz. "
            "Home Skinova = monofrequency only."
        )
