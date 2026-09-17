"""Sonotrode finite-state machine + NVM."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FSMState(str, Enum):
    IDLE_DOCKED = "IDLE_DOCKED"
    IDLE_UNDOCKED = "IDLE_UNDOCKED"
    PROGRAMMED_WAIT = "PROGRAMMED_WAIT"
    RUNNING = "RUNNING"
    PAUSED_NO_CONTACT = "PAUSED_NO_CONTACT"
    FAULT_OVERTEMP = "FAULT_OVERTEMP"
    FAULT_MOTION = "FAULT_MOTION"
    FAULT_BATTERY = "FAULT_BATTERY"
    FINISHED = "FINISHED"
    LOCKED_NEEDS_STATION = "LOCKED_NEEDS_STATION"


@dataclass
class NVM:
    program_id: int | None = None
    program_name: str = ""
    f0_hz: float = 10e6
    mode: str = "PR_1_2"
    i_set: float = 0.3
    t_remaining_s: float = 0.0
    t_total_s: float = 0.0
    session_counter: int = 0
    max_sessions: int | None = None  # None = unlimited
    serial: str = "SIM-0001"
    prf_hz: float = 100.0
    zones: list[str] = field(default_factory=lambda: ["face"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "program_name": self.program_name,
            "f0_hz": self.f0_hz,
            "mode": self.mode,
            "i_set": self.i_set,
            "t_remaining_s": self.t_remaining_s,
            "t_total_s": self.t_total_s,
            "session_counter": self.session_counter,
            "max_sessions": self.max_sessions,
            "serial": self.serial,
            "prf_hz": self.prf_hz,
            "zones": list(self.zones),
        }


class SonotrodeFSM:
    """Behavioural MCU state machine for the wireless handpiece."""

    def __init__(
        self,
        model: str = "SKINOVA_19",
        *,
        t_warn_c: float = 41.0,
        t_off_c: float = 43.0,
        motion_still_s: float = 2.0,
        motion_eps: float = 0.05,
        has_sensors: bool = True,
    ) -> None:
        self.model = model
        self.t_warn_c = t_warn_c
        self.t_off_c = t_off_c
        self.motion_still_s = motion_still_s
        self.motion_eps = motion_eps
        self.has_sensors = has_sensors or model == "SKINOVA_19"
        self.state = FSMState.IDLE_DOCKED
        self.nvm = NVM()
        self.docked = True
        self.still_timer_s = 0.0
        self.t_piezo_c = 25.0
        self.history: list[str] = [self.state.value]

    def _set(self, new: FSMState) -> None:
        if new != self.state:
            self.state = new
            self.history.append(new.value)

    def dock(self) -> None:
        self.docked = True
        if self.state in (
            FSMState.IDLE_UNDOCKED,
            FSMState.FINISHED,
            FSMState.LOCKED_NEEDS_STATION,
            FSMState.FAULT_BATTERY,
        ):
            self._set(FSMState.IDLE_DOCKED)

    def undock(self) -> None:
        self.docked = False
        if self.state == FSMState.IDLE_DOCKED:
            if self.nvm.program_id is not None and self.nvm.t_remaining_s > 0:
                self._set(FSMState.PROGRAMMED_WAIT)
            else:
                self._set(FSMState.IDLE_UNDOCKED)

    def write_program(
        self,
        program_id: int,
        name: str,
        f0_hz: float,
        mode: str,
        i_set: float,
        duration_s: float,
        prf_hz: float = 100.0,
        zones: list[str] | None = None,
    ) -> None:
        if not self.docked:
            raise RuntimeError("write_program requires docked sonotrode")
        if self.nvm.max_sessions is not None and self.nvm.session_counter >= self.nvm.max_sessions:
            self._set(FSMState.LOCKED_NEEDS_STATION)
            return
        self.nvm.program_id = program_id
        self.nvm.program_name = name
        self.nvm.f0_hz = f0_hz
        self.nvm.mode = mode
        self.nvm.i_set = i_set
        self.nvm.t_remaining_s = min(duration_s, 720.0)
        self.nvm.t_total_s = self.nvm.t_remaining_s
        self.nvm.prf_hz = prf_hz
        self.nvm.zones = zones or ["face"]
        self._set(FSMState.IDLE_DOCKED)

    def start(self) -> bool:
        if self.state in (FSMState.PROGRAMMED_WAIT, FSMState.PAUSED_NO_CONTACT, FSMState.IDLE_UNDOCKED):
            if self.nvm.program_id is None or self.nvm.t_remaining_s <= 0:
                return False
            if self.nvm.max_sessions is not None and self.nvm.session_counter >= self.nvm.max_sessions:
                self._set(FSMState.LOCKED_NEEDS_STATION)
                return False
            self.still_timer_s = 0.0
            self._set(FSMState.RUNNING)
            return True
        if self.state == FSMState.IDLE_DOCKED and self.nvm.program_id is not None:
            # Allow start while conceptually undocking
            self.docked = False
            self._set(FSMState.RUNNING)
            return True
        return False

    def pause(self) -> None:
        if self.state == FSMState.RUNNING:
            self._set(FSMState.PAUSED_NO_CONTACT)

    def reset_session(self) -> None:
        self.nvm.t_remaining_s = self.nvm.t_total_s
        self.still_timer_s = 0.0
        self.t_piezo_c = 25.0
        if self.docked:
            self._set(FSMState.IDLE_DOCKED)
        elif self.nvm.program_id is not None:
            self._set(FSMState.PROGRAMMED_WAIT)
        else:
            self._set(FSMState.IDLE_UNDOCKED)

    def tick(
        self,
        dt_s: float,
        *,
        contact: bool,
        t_piezo_c: float,
        motion_variance: float,
        soc: float,
        emitting: bool,
    ) -> FSMState:
        self.t_piezo_c = t_piezo_c

        if self.state == FSMState.RUNNING:
            # Battery
            if soc <= 0.02:
                self._set(FSMState.FAULT_BATTERY)
                return self.state

            # Temperature (model 19 sensors; optional heuristic for others)
            if self.has_sensors or self.model == "SKINOVA_19":
                if t_piezo_c >= self.t_off_c:
                    self._set(FSMState.FAULT_OVERTEMP)
                    return self.state

            # Motion stillness
            if self.has_sensors or self.model == "SKINOVA_19":
                if motion_variance < self.motion_eps:
                    self.still_timer_s += dt_s
                    if self.still_timer_s >= self.motion_still_s:
                        self._set(FSMState.FAULT_MOTION)
                        return self.state
                else:
                    self.still_timer_s = 0.0

            # Contact loss
            if not contact:
                self._set(FSMState.PAUSED_NO_CONTACT)
                return self.state

            # Timer
            if emitting:
                self.nvm.t_remaining_s = max(0.0, self.nvm.t_remaining_s - dt_s)
                if self.nvm.t_remaining_s <= 0:
                    self.nvm.session_counter += 1
                    self._set(FSMState.FINISHED)
                    return self.state

        elif self.state == FSMState.PAUSED_NO_CONTACT:
            if contact and self.nvm.t_remaining_s > 0:
                self.still_timer_s = 0.0
                self._set(FSMState.RUNNING)

        return self.state
