"""The wearer's walking cadence, measured from the shin, for the auto-tempo cue.

A metronome cue works best near the wearer's own comfortable cadence, so the device measures it
while they walk well and uses it when a freeze comes. It must not be measured at the freeze itself:
steps shorten and quicken just before one, and a cue matched to that would reinforce it.

Method: a shin sensor sees one large event per stride (its own leg) and a small one for the other
leg, so the autocorrelation of the acceleration magnitude peaks at the stride time. Cadence in
steps per minute is 120 / stride time. Checked against stride times from the gyro's swing peaks on
our own recordings (--check): the two agree within a few hundredths of a second.

    tracker = CadenceTracker()
    tracker.push(magnitude_mg)                  every sample
    tracker.on_frame(frame, cue_active)         every detector frame
    tracker.cadence_spm                         None until enough steady walking has been seen

Usage: python src/cadence.py --check [files...]   (default: every CSV in data/own/raw)
"""

import sys
from collections import deque
from pathlib import Path

import numpy as np

SAMPLE_RATE_HZ = 64
WINDOW_S = 6                     # about 4-6 strides
STRIDE_RANGE_S = (0.8, 2.2)      # 55-150 steps per minute
MIN_STRENGTH = 0.4               # autocorrelation at the stride lag, 1 = perfectly periodic
WALK_LOCO_POWER = 10_000.0       # mg^2, the detector's walking gate
MAX_WALK_FREEZE_INDEX = 0.7      # steady walking sits at 0.2-0.5; a tremble is periodic too, keep it out
ESTIMATE_EVERY_FRAMES = 4        # 2 s
KEEP_ESTIMATES = 150             # the median covers the last 5 minutes of steady walking
MIN_ESTIMATES = 1                # one is enough: all 49 on our recordings were within 2.4 steps/min of the gyro


def stride_time_s(magnitude_mg, rate_hz=SAMPLE_RATE_HZ):
    """(stride time in seconds, strength 0-1) from a few seconds of walking; (None, 0.0) if no rhythm."""
    x = np.asarray(magnitude_mg, float)
    x = x - x.mean()
    energy = float(x @ x)
    if energy <= 0:
        return None, 0.0
    low, high = int(STRIDE_RANGE_S[0] * rate_hz), int(STRIDE_RANGE_S[1] * rate_hz)
    lags = np.arange(low - 1, high + 2)
    ac = np.array([x[lag:] @ x[:-lag] for lag in lags]) / energy
    peaks = [i for i in range(1, len(ac) - 1) if ac[i] >= ac[i - 1] and ac[i] > ac[i + 1]]
    if not peaks:
        return None, 0.0
    best = max(peaks, key=lambda i: ac[i])
    # Two strides are as periodic as one. Take the shortest lag that is nearly as strong as the best.
    best = next(i for i in peaks if ac[i] >= 0.85 * ac[best])
    # Parabola through the peak and its neighbours: finer than the 1/64 s sample spacing.
    a, b, c = ac[best - 1], ac[best], ac[best + 1]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0
    return (lags[best] + shift) / rate_hz, float(ac[best])


class CadenceTracker:
    def __init__(self, rate_hz=SAMPLE_RATE_HZ, initial_spm=None):
        self.rate_hz = rate_hz
        self.samples = deque(maxlen=WINDOW_S * rate_hz)
        self.estimates = deque(maxlen=KEEP_ESTIMATES)
        self.initial_spm = initial_spm   # remembered from an earlier run until this one has its own
        self.walking_frames = 0          # consecutive frames of steady walking
        self.frames_per_window = WINDOW_S * 2   # detector frames are 0.5 s apart

    def push(self, magnitude_mg):
        self.samples.append(magnitude_mg)

    def on_frame(self, frame, cue_active=False):
        """Feed every detector Frame. Returns a new estimate in steps per minute, or None."""
        steady = (frame.loco_power > WALK_LOCO_POWER and frame.freeze_index < MAX_WALK_FREEZE_INDEX
                  and not frame.cue_on and not cue_active)
        self.walking_frames = self.walking_frames + 1 if steady else 0
        # Only a window that was steady walking from end to end, and only every 2 s.
        if self.walking_frames < self.frames_per_window or len(self.samples) < self.samples.maxlen:
            return None
        if (self.walking_frames - self.frames_per_window) % ESTIMATE_EVERY_FRAMES:
            return None
        stride, strength = stride_time_s(self.samples, self.rate_hz)
        if stride is None or strength < MIN_STRENGTH:
            return None
        self.estimates.append(120.0 / stride)
        return self.estimates[-1]

    @property
    def cadence_spm(self):
        if len(self.estimates) >= MIN_ESTIMATES:
            return float(np.median(self.estimates))
        return self.initial_spm


def check(files):
    """Own recordings: every estimate against the stride time from the gyro's swing peaks."""
    import pandas as pd
    from scipy.signal import butter, find_peaks, sosfiltfilt

    from streaming_detector import StreamingDetector

    for path in files:
        data = pd.read_csv(path)
        labels = data["label"].fillna("").to_numpy()
        gyro = data[["gx_dps", "gy_dps", "gz_dps"]].to_numpy()
        swing = sosfiltfilt(butter(2, 3, "low", fs=SAMPLE_RATE_HZ, output="sos"), gyro[:, np.argmax(gyro.var(axis=0))])
        swing = swing * np.sign(swing[np.argmax(np.abs(swing))])
        peaks, _ = find_peaks(swing, height=0.5 * np.percentile(swing, 95), distance=0.6 * SAMPLE_RATE_HZ)

        detector, tracker, rows = StreamingDetector(), CadenceTracker(), []
        for i, (ax, ay, az) in enumerate(data[["ax_mg", "ay_mg", "az_mg"]].to_numpy()):
            tracker.push(float(np.sqrt(ax * ax + ay * ay + az * az)))
            frame = detector.push(ax, ay, az)
            estimate = tracker.on_frame(frame) if frame else None
            if estimate:
                inside = peaks[(peaks > i - WINDOW_S * SAMPLE_RATE_HZ) & (peaks <= i)]
                reference = 120 * SAMPLE_RATE_HZ / np.median(np.diff(inside)) if len(inside) > 2 else np.nan
                window_labels = set(labels[i - WINDOW_S * SAMPLE_RATE_HZ + 1:i + 1])
                rows.append((i / SAMPLE_RATE_HZ, estimate, reference, "+".join(sorted(window_labels))))
        print(f"\n{path.name}: {len(rows)} estimates, cadence {tracker.cadence_spm and round(tracker.cadence_spm, 1)} steps/min")
        for t, estimate, reference, names in rows:
            print(f"   {t:6.1f} s  accel {estimate:6.1f}   gyro {reference:6.1f}   window: {names}")
        if rows:
            errors = np.array([e - r for _, e, r, _ in rows])
            print(f"   accel minus gyro: median {np.nanmedian(errors):+.1f}, worst {np.nanmax(np.abs(errors)):.1f} steps/min")


if __name__ == "__main__":
    if "--check" not in sys.argv:
        raise SystemExit(__doc__)
    raw = Path(__file__).resolve().parents[2] / "data" / "own" / "raw"
    check([Path(f) for f in sys.argv[1:] if f != "--check"] or sorted(raw.glob("*.csv")))
