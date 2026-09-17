"""Programming / charging station behavioural API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.fsm_sonotrode import SonotrodeFSM


@dataclass
class ProgramBlob:
    program_id: int
    name: str
    f0_hz: float
    mode: str
    i_set: float
    duration_s: float
    prf_hz: float = 100.0
    zones: list[str] = field(default_factory=lambda: ["face"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "name": self.name,
            "f0_hz": self.f0_hz,
            "mode": self.mode,
            "i_set": self.i_set,
            "duration_s": self.duration_s,
            "prf_hz": self.prf_hz,
            "zones": list(self.zones),
        }


@dataclass
class StationSpecs:
    dimensions_mm: tuple[float, float, float] = (235.0, 115.0, 165.0)
    mass_kg: float = 0.7
    power_va: float = 18.0
    protection_class: str = "II"


class Station:
    """write(ProgramBlob) + charge()."""

    def __init__(self, specs: StationSpecs | None = None) -> None:
        self.specs = specs or StationSpecs()
        self.last_written: ProgramBlob | None = None
        self.charging = False

    def write(self, sonotrode: SonotrodeFSM, blob: ProgramBlob) -> None:
        sonotrode.dock()
        sonotrode.write_program(
            program_id=blob.program_id,
            name=blob.name,
            f0_hz=blob.f0_hz,
            mode=blob.mode,
            i_set=blob.i_set,
            duration_s=min(blob.duration_s, 720.0),
            prf_hz=blob.prf_hz,
            zones=blob.zones,
        )
        self.last_written = blob

    def charge(self, sonotrode: SonotrodeFSM, soc: float, dt_s: float, rate_per_hour: float = 1.0) -> float:
        """Charge battery while docked; returns new SoC in [0,1]."""
        sonotrode.dock()
        self.charging = True
        return min(1.0, soc + rate_per_hour * dt_s / 3600.0)

    def stop_charge(self) -> None:
        self.charging = False
