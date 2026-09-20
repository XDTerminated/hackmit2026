"""Synthetic IMU gait generator for the HackMIT demo.

Walking: ~baseline cadence oscillation on accel magnitude.
Freeze-like: collapsed stepping amplitude + higher-frequency tremor.
Never labeled as clinically confirmed FoG.
"""

from __future__ import annotations

import math
import random
import time
from typing import Literal

from models import IMUSample

GaitMode = Literal["walking", "freeze", "recovering"]


class GaitSimulator:
    def __init__(self, baseline_cadence_bpm: float = 102.0) -> None:
        self.baseline_cadence_bpm = baseline_cadence_bpm
        self.cadence_bpm = baseline_cadence_bpm
        self.mode: GaitMode = "walking"
        self._t0 = time.perf_counter()
        self._last_t = 0.0
        self._phase = 0.0  # accumulated step phase (rad) — avoids f*t phase jumps
        self._blend = 1.0  # 1 = walking, 0 = freeze-like
        self._noise = random.Random(2026)

    def set_mode(self, mode: GaitMode) -> None:
        self.mode = mode

    def reset(self, baseline_cadence_bpm: float | None = None) -> None:
        if baseline_cadence_bpm is not None:
            self.baseline_cadence_bpm = baseline_cadence_bpm
        self.cadence_bpm = self.baseline_cadence_bpm
        self.mode = "walking"
        self._t0 = time.perf_counter()
        self._last_t = 0.0
        self._phase = 0.0
        self._blend = 1.0

    def sample(self) -> IMUSample:
        t = time.perf_counter() - self._t0
        dt = max(0.0, min(0.2, t - self._last_t))
        self._last_t = t
        target = 1.0 if self.mode == "walking" else 0.0
        if self.mode == "recovering":
            target = 1.0
        # Smooth visual blend so judges see the waveform morph.
        blend_rate = 0.07 if self.mode == "recovering" else 0.12
        self._blend += (target - self._blend) * blend_rate

        step_hz = max(0.4, self.cadence_bpm / 60.0)
        self._phase += 2 * math.pi * step_hz * dt
        ph = self._phase
        walk_amp = 2.35 * self._blend
        freeze_amp = 0.12 * (1.0 - self._blend)
        tremor = (1.0 - self._blend) * 0.55 * math.sin(2 * math.pi * 7.5 * t)

        n = lambda s: self._noise.gauss(0.0, s)
        # Heel-strike asymmetry: sharper impacts, timing drift, and a softer
        # swing trough. These are still synthetic Demo samples, never labels.
        phase_drift = 0.035 * math.sin(2 * math.pi * 0.23 * t) + n(0.012) * self._blend
        ph_view = ph + phase_drift
        impact = max(0.0, math.sin(ph_view + 0.18)) ** 5
        stride = math.sin(ph_view) + 0.28 * math.sin(2 * ph_view + 0.6) + 0.18 * impact
        # Freeze-like stalls interrupt the rhythm before small irregular motion
        # returns, making the contrast visible without violent shaking.
        stall = 1.0
        if self.mode == "freeze":
            stall = 0.42 + 0.58 * max(0.0, math.sin(2 * math.pi * 0.38 * t + 0.7))
        osc = walk_amp * stride * stall + freeze_amp * math.sin(2 * math.pi * 0.7 * t)
        ax = 0.18 * math.sin(ph + 0.4) * self._blend + n(0.02)
        ay = -0.35 * math.cos(ph) * self._blend + n(0.02)
        az = 9.73 + osc + tremor + n(0.03)
        gx = (18.0 * self._blend) * math.sin(ph) + n(0.3)
        gy = (9.0 * self._blend) * math.cos(ph) + n(0.3)
        gz = n(0.2) + (1.0 - self._blend) * 2.2 * math.sin(2 * math.pi * 7.5 * t)

        accel_mag = math.sqrt(ax * ax + ay * ay + az * az)
        gyro_mag = math.sqrt(gx * gx + gy * gy + gz * gz)

        # Keep Demo cadence plausible. Only a freeze-like phase lowers it, and
        # it does so gradually instead of jumping to values such as 22 BPM.
        if self.mode == "freeze":
            target_cadence = self.baseline_cadence_bpm * (0.62 + 0.38 * self._blend)
        elif self.mode == "recovering":
            target_cadence = self.baseline_cadence_bpm * (0.82 + 0.18 * self._blend)
        else:
            target_cadence = self.baseline_cadence_bpm
        self.cadence_bpm += (target_cadence - self.cadence_bpm) * 0.2 + n(0.15) * self._blend

        return IMUSample(
            timestamp=round(t * 1000.0, 2),
            ax=round(ax, 4),
            ay=round(ay, 4),
            az=round(az, 4),
            gx=round(gx, 3),
            gy=round(gy, 3),
            gz=round(gz, 3),
            accel_mag=round(accel_mag, 4),
            gyro_mag=round(gyro_mag, 3),
            cadence_bpm=round(self.cadence_bpm, 1),
        )
