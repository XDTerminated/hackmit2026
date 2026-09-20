"""Sample-at-a-time freeze detector: the one detector, as it runs on the board.

One sample in, a fixed ring buffer, an FFT every STEP samples, then the cue state machine with a
handful of scalar state variables. No look-ahead, no growing memory. This is also the reference for a
future STM32 port; test_vectors/README.md is its specification.

    detector = StreamingDetector()
    frame = detector.push(ax_mg, ay_mg, az_mg)   # None, or a Frame every 0.5 s

Shipped to the board with device_server.py, so it must import with NumPy alone. Checking it against
the batch analysis code and against test_vectors/ is analysis/verify_detector.py.
"""

import math
from collections import deque
from dataclasses import asdict, dataclass

import numpy as np

# pandas (for run()) and scipy (a faster FFT) are optional: on the UNO Q neither may be installed.
try:
    import pandas as pd
except ImportError:
    pd = None
try:
    from scipy import fft as sp_fft
except ImportError:
    sp_fft = np.fft


@dataclass(frozen=True)
class DetectorParams:
    sample_rate_hz: int = 64
    window: int = 256              # samples (4 s); FFT length
    step: int = 32                 # samples (0.5 s) between frames
    # Window weights rise linearly from 0 (oldest sample) to 1 (newest), to this power. Old
    # movement then counts for little, so a freeze straight after walking is caught ~1 s sooner
    # for about the same false-alarm rate (latency_experiment.py). 0 = unweighted.
    ramp_power: int = 1
    # FFT bin k is k * sample_rate / window = k * 0.25 Hz
    loco_bins: tuple = (2, 12)     # 0.5 Hz <= f < 3 Hz   -> k = 2..11
    freeze_bins: tuple = (12, 33)  # 3 Hz <= f <= 8 Hz    -> k = 12..32
    fi_threshold: float = 1.056
    power_threshold: float = 178.0       # mg^2, loco + freeze band power
    # A window whose band power is below this fraction of the previous window's is never positive:
    # power that is still collapsing is the wearer stopping, not freezing (0 disables the rule).
    # Provisional: tuned on two volunteers, see stop_veto_experiment.py.
    stop_veto_ratio: float = 0.6
    walk_loco_power: float = 10_000.0    # mg^2, loco band power that counts as walking
    debounce_frames: int = 2
    gate_lookback_frames: int = 10       # 5 s
    gate_min_walk_frames: int = 2        # 1 s
    hold_frames: int = 10                # 5 s


# The sensitivity presets of docs/api.md, as overrides of DetectorParams. The numbers live here, never in the app.
PRESETS = {
    "catch_more": dict(debounce_frames=1),
    "balanced": dict(),
    "fewer_alerts": dict(fi_threshold=1.656, power_threshold=13_335.0),
}


@dataclass
class Frame:
    sample_index: int      # index of the newest sample in the window, 0-based since reset
    freeze_index: float
    total_power: float     # mg^2
    loco_power: float      # mg^2
    positive: bool         # raw detector output for this window
    armed: bool            # walking gate state when this frame was evaluated
    cue_on: bool           # what the buzzer does
    stopping: bool = False # the stop rule rejected this window (band power still collapsing)


class SampleClock:
    """Timing of the incoming sample stream, from the STM32's micros() timestamps.

    rate_hz is the number of samples delivered per second of device time over the last ~10 s
    (None until a second of data has arrived). Averaging 1/dt per sample instead reads high
    whenever there is timing jitter. lost counts sampling slots that produced no sample.
    """

    def __init__(self, nominal_hz=64, window_s=10):
        self.period_us = 1_000_000 / nominal_hz
        self.rate_hz = None
        self.lost = 0
        self._min_samples = nominal_hz
        self._last_t_us = None
        self._elapsed_us = 0
        self._recent = deque(maxlen=nominal_hz * window_s + 1)

    def tick(self, t_us):
        t_us = int(t_us)
        if self._last_t_us is not None:
            dt = (t_us - self._last_t_us) % 2**32   # micros() wraps every ~71 minutes
            self.lost += max(round(dt / self.period_us) - 1, 0)
            self._elapsed_us += dt
            self._recent.append(self._elapsed_us)
            span = self._recent[-1] - self._recent[0]
            if len(self._recent) > self._min_samples and span:
                self.rate_hz = (len(self._recent) - 1) * 1_000_000 / span
        self._last_t_us = t_us


class StreamingDetector:
    def __init__(self, params=DetectorParams(), dtype=np.float64):
        self.p = params
        self.dtype = dtype
        self.reset()

    def reset(self):
        p = self.p
        self.buffer = np.zeros(p.window, self.dtype)
        self.weights = (np.linspace(0, 1, p.window) ** p.ramp_power if p.ramp_power else np.ones(p.window)).astype(self.dtype)
        self.weight_sum = self.weights.sum(dtype=self.dtype)
        self.weight_sq_sum = (self.weights**2).sum(dtype=self.dtype)
        self.head = 0               # next write position
        self.n_samples = 0
        self.walk_history = [False] * p.gate_lookback_frames  # ring buffer of walking flags
        self.walk_head = 0
        self.consecutive = 0
        self.cue_on = False
        self.hold_end = 0           # frame number before which the cue may not stop
        self.previous_power = None  # band power of the previous frame, for the stop veto
        self.n_frames = 0

    def push(self, ax_mg, ay_mg, az_mg):
        """Feed one accelerometer sample in milli-g."""
        return self.push_magnitude(math.sqrt(ax_mg * ax_mg + ay_mg * ay_mg + az_mg * az_mg))

    def push_magnitude(self, magnitude_mg):
        p = self.p
        self.buffer[self.head] = magnitude_mg
        self.head = (self.head + 1) % p.window
        self.n_samples += 1
        if self.n_samples < p.window or (self.n_samples - p.window) % p.step:
            return None
        return self._frame()

    def _frame(self):
        p = self.p
        # Put the ring buffer in time order (oldest first): the weights depend on sample age.
        x = np.concatenate([self.buffer[self.head:], self.buffer[:self.head]])
        weighted_mean = (x * self.weights).sum(dtype=self.dtype) / self.weight_sum
        spectrum = sp_fft.rfft((x - weighted_mean) * self.weights)
        # Scaled so that a band sum is the signal variance inside that band (mg^2).
        scale = self.dtype(2.0 / (p.window * self.weight_sq_sum))
        bin_power = (spectrum.real**2 + spectrum.imag**2) * scale
        loco = float(bin_power[p.loco_bins[0]:p.loco_bins[1]].sum(dtype=self.dtype))
        freeze = float(bin_power[p.freeze_bins[0]:p.freeze_bins[1]].sum(dtype=self.dtype))

        freeze_index = freeze / max(loco, 1e-9)
        total = loco + freeze
        stopping = self.previous_power is not None and total < p.stop_veto_ratio * self.previous_power
        self.previous_power = total
        positive = freeze_index > p.fi_threshold and total > p.power_threshold and not stopping

        # Cue state machine (same as simulate_device.cue_logic)
        i = self.n_frames
        self.consecutive = self.consecutive + 1 if positive else 0
        armed = sum(self.walk_history) >= p.gate_min_walk_frames
        if self.cue_on:
            # The gate only controls when a cue may start: a long freeze has no recent walking.
            self.cue_on = positive or i < self.hold_end
        if not self.cue_on and positive and armed and self.consecutive >= p.debounce_frames:
            self.cue_on = True
            self.hold_end = i + p.hold_frames

        self.walk_history[self.walk_head] = loco > p.walk_loco_power
        self.walk_head = (self.walk_head + 1) % p.gate_lookback_frames
        self.n_frames += 1
        return Frame(self.n_samples - 1, freeze_index, total, loco, positive, armed, self.cue_on, stopping)


def run(detector, magnitudes=None, axes=None):
    """Reset the detector, feed a whole recording, return its frames as a DataFrame."""
    detector.reset()
    if axes is not None:
        frames = [detector.push(*row) for row in axes]
    else:
        frames = [detector.push_magnitude(m) for m in magnitudes]
    return pd.DataFrame([asdict(f) for f in frames if f is not None])
