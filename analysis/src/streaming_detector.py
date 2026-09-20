"""Sample-at-a-time freeze detector: the reference implementation for the STM32 port.

baseline_fi.py and simulate_device.py work on whole recordings with NumPy. This
file does the same computation the way the microcontroller will: one sample in,
a fixed ring buffer, an FFT every STEP samples, then the cue state machine with
a handful of scalar state variables. No look-ahead, no growing memory.

    detector = StreamingDetector()
    frame = detector.push(ax_mg, ay_mg, az_mg)   # None, or a Frame every 0.5 s

Commands:
  python src/streaming_detector.py --verify          check it reproduces the batch code on all
                                                     of Daphnet, and what float32 changes
  python src/streaming_detector.py --export          write test vectors to test_vectors/
  python src/streaming_detector.py --check-vectors   check it still reproduces test_vectors/
  (no flag: --verify then --export)
"""

import argparse
import math
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

# pandas and scipy are only needed for --verify / --export on a laptop. The detector itself runs
# on the UNO Q, where neither may be installed.
try:
    import pandas as pd
except ImportError:
    pd = None
try:
    from scipy import fft as sp_fft
except ImportError:
    sp_fft = np.fft

ROOT = Path(__file__).resolve().parents[2]  # repo root
CLEAN_DIR = ROOT / "data" / "daphnet" / "clean"
VECTOR_DIR = ROOT / "test_vectors"


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


def verify():
    from baseline_fi import STEP_S, window_features
    from simulate_device import CueConfig, cue_logic, stop_veto

    p = DetectorParams()
    cfg = CueConfig("reference", debounce=p.debounce_frames, gate_lookback_s=p.gate_lookback_frames * STEP_S,
                    gate_min_walk_s=p.gate_min_walk_frames * STEP_S, hold_s=p.hold_frames * STEP_S)
    exact, single = StreamingDetector(p), StreamingDetector(p, np.float32)

    n_frames = worst_fi = worst_power = 0
    cue_mismatch = axes_cue_diff = f32_positive_diff = f32_cue_diff = 0
    f32_worst = 0.0
    for path in sorted(CLEAN_DIR.glob("S*.csv")):
        for _, seg in pd.read_csv(path).groupby("segment"):
            mag = seg["acc_mag"].to_numpy()
            fi, power, _ = window_features(mag, p.window, p.step, p.ramp_power)
            cue = cue_logic(fi, power, p.fi_threshold, p.power_threshold, cfg, stop_veto(power, p.stop_veto_ratio))

            got = run(exact, magnitudes=mag)
            n_frames += len(got)
            worst_fi = max(worst_fi, np.max(np.abs(got.freeze_index - fi) / np.maximum(fi, 1e-12)))
            worst_power = max(worst_power, np.max(np.abs(got.total_power - power) / np.maximum(power, 1e-12)))
            cue_mismatch += int((got.cue_on.to_numpy() != cue).sum())

            # What the device will really do: magnitude from the three axes, in float32.
            from_axes = run(exact, axes=seg[["acc_f", "acc_v", "acc_l"]].to_numpy())
            axes_cue_diff += int((from_axes.cue_on != got.cue_on).sum())
            f32 = run(single, axes=seg[["acc_f", "acc_v", "acc_l"]].to_numpy().astype(np.float32))
            f32_positive_diff += int((f32.positive != from_axes.positive).sum())
            f32_cue_diff += int((f32.cue_on != from_axes.cue_on).sum())
            f32_worst = max(f32_worst, np.max(np.abs(f32.freeze_index - from_axes.freeze_index)
                                              / np.maximum(from_axes.freeze_index, 1e-12)))
        print(f"  {path.stem} checked", flush=True)

    print(f"\n{n_frames} frames compared with the batch code (baseline_fi + simulate_device):")
    print(f"  max relative error: freeze index {worst_fi:.1e}, total power {worst_power:.1e}")
    print(f"  cue on/off mismatches: {cue_mismatch}")
    print(f"magnitude computed from the 3 axes instead of the stored acc_mag column: {axes_cue_diff} cue frames differ")
    print(f"float32 instead of float64: max relative freeze-index error {f32_worst:.1e}, "
          f"{f32_positive_diff} raw decisions and {f32_cue_diff} cue frames differ")
    ok = cue_mismatch == 0 and worst_fi < 1e-6 and worst_power < 1e-6
    print("VERIFY " + ("PASSED" if ok else "FAILED"))
    return ok


# (name, subject, what to look for, chunk length in seconds)
SCENARIOS = [
    ("walk_then_freeze", "cue starts after walking runs into a freeze", 60),
    ("standing_still", "power below threshold the whole time, cue never on", 60),
    ("gate_blocked", "detector positive but no recent walking, so the cue must stay off", 60),
    ("long_freeze", "cue must keep playing through a long freeze after the gate has lapsed", 90),
]


def find_chunks():
    """Locate one chunk of cleaned data for each scenario. Returns {name: (subject, segment, start, stop)}."""
    p = DetectorParams()
    detector = StreamingDetector(p)
    lengths = {name: seconds * p.sample_rate_hz for name, _, seconds in SCENARIOS}
    found = {}
    longest_freeze = 0
    for path in sorted(CLEAN_DIR.glob("S*.csv")):
        for seg_id, seg in pd.read_csv(path).groupby("segment"):
            frames = run(detector, magnitudes=seg["acc_mag"].to_numpy())
            freeze = seg["freeze"].to_numpy().astype(bool)
            n = len(seg)

            def chunk(name, centre):
                start = int(np.clip(centre - lengths[name] // 2, 0, max(n - lengths[name], 0)))
                return path.stem, seg_id, start, min(start + lengths[name], n)

            starts = frames.sample_index[frames.cue_on & ~frames.cue_on.shift(fill_value=False)]
            if "walk_then_freeze" not in found:
                for s in starts:
                    if freeze[s] and not freeze[max(s - 20 * p.sample_rate_hz, 0):s - 3 * p.sample_rate_hz].any():
                        found["walk_then_freeze"] = chunk("walk_then_freeze", s)
                        break
            if "standing_still" not in found:
                quiet = (frames.total_power < p.power_threshold).rolling(lengths["standing_still"] // p.step).sum()
                hit = frames.sample_index[quiet == lengths["standing_still"] // p.step]
                if len(hit):
                    found["standing_still"] = chunk("standing_still", hit.iloc[0] - lengths["standing_still"] // 2)
            if "gate_blocked" not in found:
                blocked = frames.positive & frames.positive.shift(fill_value=False) & ~frames.armed & ~frames.cue_on
                if blocked.sum() >= 4:
                    found["gate_blocked"] = chunk("gate_blocked", frames.sample_index[blocked].iloc[0])

            edges = np.flatnonzero(np.diff(np.concatenate([[0], freeze.astype(int), [0]])))
            for s, e in zip(edges[::2], edges[1::2]):
                cued = frames.cue_on[(frames.sample_index >= s) & (frames.sample_index < e)]
                if e - s > longest_freeze and e - s < 60 * p.sample_rate_hz and len(cued) and cued.mean() > 0.7:
                    longest_freeze = e - s
                    found["long_freeze"] = chunk("long_freeze", (s + e) // 2)
    return found


def export():
    p = DetectorParams()
    detector = StreamingDetector(p)
    VECTOR_DIR.mkdir(exist_ok=True)
    chunks = find_chunks()
    summary = []
    for name, description, _ in SCENARIOS:
        if name not in chunks:
            print(f"  no chunk found for {name}")
            continue
        subject, seg_id, start, stop = chunks[name]
        df = pd.read_csv(CLEAN_DIR / f"{subject}.csv")
        part = df[df.segment == seg_id].iloc[start:stop]
        axes = part[["acc_f", "acc_v", "acc_l"]].to_numpy()

        frames = run(detector, axes=axes)  # fresh state: exactly what the C code will see
        frames["label_freeze"] = part["freeze"].to_numpy()[frames.sample_index]
        for col in ("positive", "armed", "cue_on"):
            frames[col] = frames[col].astype(int)

        pd.DataFrame(axes, columns=["ax_mg", "ay_mg", "az_mg"]).to_csv(
            VECTOR_DIR / f"{name}_input.csv", index=False, float_format="%.1f")
        frames.to_csv(VECTOR_DIR / f"{name}_expected.csv", index=False, float_format="%.6g")
        summary.append(dict(vector=name, source=f"{subject} seg {seg_id} @{start / p.sample_rate_hz:.0f}s",
                            samples=len(axes), frames=len(frames), positive=frames.positive.sum(),
                            armed=frames.armed.sum(), cue_on=frames.cue_on.sum(),
                            labelled_freeze=frames.label_freeze.sum(), checks=description))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 90)
    print(pd.DataFrame(summary).to_string(index=False))
    print(f"\nWrote test vectors to {VECTOR_DIR}")


def check_vectors():
    """Replay every test vector and compare with its expected file, as the C port will have to."""
    ok = True
    for expected_path in sorted(VECTOR_DIR.glob("*_expected.csv")):
        expected = pd.read_csv(expected_path)
        axes = pd.read_csv(str(expected_path).replace("_expected", "_input")).to_numpy()
        got = run(StreamingDetector(), axes=axes)
        same = len(got) == len(expected) and all(
            (got[c].astype(int) == expected[c]).all() for c in ("positive", "armed", "cue_on")
        ) and np.allclose(got["freeze_index"], expected["freeze_index"], rtol=1e-4)
        print(f"  {expected_path.name}: {len(got)} frames {'match' if same else 'DIFFER'}")
        ok &= same
    print("CHECK " + ("PASSED" if ok else "FAILED: the detector no longer matches test_vectors/ (re-export if intended)"))
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--check-vectors", action="store_true")
    args = parser.parse_args()
    if args.check_vectors:
        raise SystemExit(0 if check_vectors() else 1)
    if not CLEAN_DIR.exists():
        raise SystemExit(f"No cleaned data in {CLEAN_DIR}; run clean_daphnet.py first")
    both = not (args.verify or args.export)
    if args.verify or both:
        if not verify():
            raise SystemExit(1)
    if args.export or both:
        export()


if __name__ == "__main__":
    main()
