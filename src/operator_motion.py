"""Operator path models: circle / linear / still; force → gel thickness."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

import numpy as np


class PathType(str, Enum):
    CIRCLE = "circle"
    LINEAR = "linear"
    STILL = "still"


@dataclass
class MotionSample:
    x_m: float
    y_m: float
    speed_m_s: float
    accel_var: float
    gel_thickness_m: float
    force_n: float


class OperatorMotion:
    """Synthetic handpiece trajectory."""

    def __init__(
        self,
        path: PathType | str = PathType.CIRCLE,
        radius_m: float = 0.015,
        speed_m_s: float = 0.020,
        force_n: float = 1.0,
        gel0_m: float = 0.0003,
        k_force: float = 0.5,
        seed: int | None = 42,
    ) -> None:
        self.path = PathType(path) if not isinstance(path, PathType) else path
        self.radius_m = radius_m
        self.speed_m_s = speed_m_s
        self.force_n = force_n
        self.gel0_m = gel0_m
        self.k_force = k_force
        self._rng = np.random.default_rng(seed)
        self._t = 0.0
        self._lin_dir = 1.0
        self._lin_pos = 0.0
        self._prev_speed = speed_m_s

    def gel_thickness(self) -> float:
        return self.gel0_m / (1.0 + self.k_force * self.force_n)

    def sample(self, dt_s: float) -> MotionSample:
        self._t += dt_s
        if self.path == PathType.STILL:
            x, y = 0.0, 0.0
            speed = 0.0
            accel_var = 0.0
        elif self.path == PathType.CIRCLE:
            omega = self.speed_m_s / max(self.radius_m, 1e-6)
            ang = omega * self._t
            x = self.radius_m * math.cos(ang)
            y = self.radius_m * math.sin(ang)
            speed = self.speed_m_s
            # Acceleration magnitude for circular motion ≈ ω²r; variance proxy
            accel_var = abs(omega * omega * self.radius_m) + float(self._rng.normal(0, 0.01))
            accel_var = abs(accel_var)
        else:  # LINEAR
            self._lin_pos += self._lin_dir * self.speed_m_s * dt_s
            if abs(self._lin_pos) > self.radius_m:
                self._lin_dir *= -1.0
            x, y = self._lin_pos, 0.0
            speed = self.speed_m_s
            accel_var = abs(speed - self._prev_speed) / max(dt_s, 1e-6) + 0.1

        self._prev_speed = speed
        return MotionSample(
            x_m=x,
            y_m=y,
            speed_m_s=speed,
            accel_var=accel_var,
            gel_thickness_m=self.gel_thickness(),
            force_n=self.force_n,
        )

    def set_path(self, path: PathType | str) -> None:
        self.path = PathType(path) if not isinstance(path, PathType) else path
        self._t = 0.0
