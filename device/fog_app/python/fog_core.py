"""Core of the Freezing of Gait Monitor: detector, live state, labelled recording.

No Arduino imports, so the same code runs on the UNO Q (from main.py) and on a laptop
(from ../dev_server.py). Only needs numpy.

The detector is a copy of analysis/src/streaming_detector.py, which is the reference; the
constants and algorithm are specified in test_vectors/README.md. `python fog_core.py` checks
this copy against the test vectors.
"""

import csv
import math
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SAMPLE_RATE_HZ = 64
SAMPLE_PERIOD_US = 1_000_000 / SAMPLE_RATE_HZ
WINDOW, STEP = 256, 32                 # 4 s window, a frame every 0.5 s
LOCO_BINS, FREEZE_BINS = slice(2, 12), slice(12, 33)   # 0.5-3 Hz and 3-8 Hz at 0.25 Hz per bin
FI_THRESHOLD = 1.056
POWER_THRESHOLD = 178.0                # mg^2
WALK_LOCO_POWER = 10_000.0             # mg^2
# Positive frames in a row needed to start a cue. 2 = balanced, 1 = fast (about 0.5 s sooner,
# roughly 20-30% more false cues on the patient datasets).
RESPONSE_DEBOUNCE = {"balanced": 2, "fast": 1}
# Window weights rise linearly from 0 (oldest sample) to 1 (newest), so a freeze straight after
# walking is caught about a second sooner than with an unweighted window.
WEIGHTS = np.linspace(0, 1, WINDOW)
WEIGHT_SUM, WEIGHT_SQ_SUM = WEIGHTS.sum(), (WEIGHTS**2).sum()
GATE_LOOKBACK_FRAMES, GATE_MIN_WALK_FRAMES = 10, 2
HOLD_FRAMES = 10

LABELS = ("walking", "standing", "freezing")
RECORDING_COLUMNS = ["t_us", "ax_mg", "ay_mg", "az_mg", "gx_dps", "gy_dps", "gz_dps", "label"]


class Detector:
    """Sample-at-a-time Freeze Index detector with the cue state machine."""

    def __init__(self):
        self.debounce = RESPONSE_DEBOUNCE["balanced"]
        self.buffer = np.zeros(WINDOW)
        self.head = 0
        self.n_samples = 0
        self.walk_history = [False] * GATE_LOOKBACK_FRAMES
        self.walk_head = 0
        self.consecutive = 0
        self.cue_on = False
        self.hold_end = 0
        self.n_frames = 0

    def push(self, ax_mg, ay_mg, az_mg):
        """Feed one sample. Returns a frame dict every STEP samples once the window is full, else None."""
        self.buffer[self.head] = math.sqrt(ax_mg * ax_mg + ay_mg * ay_mg + az_mg * az_mg)
        self.head = (self.head + 1) % WINDOW
        self.n_samples += 1
        if self.n_samples < WINDOW or (self.n_samples - WINDOW) % STEP:
            return None

        # Ring buffer into time order (oldest first), because the weights depend on sample age.
        x = np.concatenate([self.buffer[self.head:], self.buffer[:self.head]])
        spectrum = np.fft.rfft((x - (x * WEIGHTS).sum() / WEIGHT_SUM) * WEIGHTS)
        bin_power = (spectrum.real**2 + spectrum.imag**2) * (2.0 / (WINDOW * WEIGHT_SQ_SUM))
        loco = float(bin_power[LOCO_BINS].sum())
        freeze = float(bin_power[FREEZE_BINS].sum())
        freeze_index = freeze / max(loco, 1e-9)
        total = loco + freeze
        positive = freeze_index > FI_THRESHOLD and total > POWER_THRESHOLD

        i = self.n_frames
        self.consecutive = self.consecutive + 1 if positive else 0
        armed = sum(self.walk_history) >= GATE_MIN_WALK_FRAMES
        if self.cue_on:
            # The gate only controls when a cue may start: a long freeze has no recent walking.
            self.cue_on = positive or i < self.hold_end
        if not self.cue_on and positive and armed and self.consecutive >= self.debounce:
            self.cue_on = True
            self.hold_end = i + HOLD_FRAMES
        self.walk_history[self.walk_head] = loco > WALK_LOCO_POWER
        self.walk_head = (self.walk_head + 1) % GATE_LOOKBACK_FRAMES
        self.n_frames += 1

        return dict(sample_index=self.n_samples - 1, freeze_index=freeze_index, total_power=total,
                    loco_power=loco, positive=positive, armed=armed, cue_on=self.cue_on)


class FogCore:
    """Thread-safe hub: samples come in from the Bridge thread, the web server reads state out."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.lock = threading.Lock()
        self.detector = Detector()
        self.magnitudes = deque(maxlen=SAMPLE_RATE_HZ * 15)   # (sample number, |acc| mg)
        self.frames = deque(maxlen=240)                       # 2 minutes of frames
        self.events = deque(maxlen=200)
        self.open_event = None
        self.n_samples = 0
        self.lost_samples = 0
        self.last_t_us = None
        self.device_time_us = 0
        self.recent_times = deque(maxlen=SAMPLE_RATE_HZ * 10 + 1)
        self.rate_hz = None
        self.last_sample_time = None
        self.chip_id = None
        self.recording = None        # dict(name, file, writer, rows) while recording
        self.label = ""

    # ---- input -------------------------------------------------------------------------------

    def add_sample(self, t_us, ax, ay, az, gx, gy, gz):
        """Feed one IMU sample. Returns True/False when the cue should switch on/off, else None."""
        with self.lock:
            t_us = int(t_us)
            if self.last_t_us is not None:
                dt = (t_us - self.last_t_us) % 2**32          # micros() wraps every ~71 minutes
                self.lost_samples += max(round(dt / SAMPLE_PERIOD_US) - 1, 0)
                # Samples delivered per second of device time over the last ~10 s. (Averaging 1/dt
                # per sample instead reads high whenever there is timing jitter.)
                self.device_time_us += dt
                self.recent_times.append(self.device_time_us)
                if len(self.recent_times) > SAMPLE_RATE_HZ:
                    span = self.recent_times[-1] - self.recent_times[0]
                    self.rate_hz = (len(self.recent_times) - 1) * 1_000_000 / span if span else None
            self.last_t_us = t_us
            self.last_sample_time = time.monotonic()
            self.n_samples += 1

            if self.recording:
                self.recording["writer"].writerow(
                    [t_us, f"{ax:.1f}", f"{ay:.1f}", f"{az:.1f}", f"{gx:.1f}", f"{gy:.1f}", f"{gz:.1f}", self.label])
                self.recording["rows"] += 1

            was_on = self.detector.cue_on
            frame = self.detector.push(ax, ay, az)
            self.magnitudes.append((self.n_samples, round(self.detector.buffer[self.detector.head - 1], 1)))
            if frame is None:
                return None

            frame["n"] = self.detector.n_frames
            frame["state"] = self._state_name(frame)
            self.frames.append(frame)
            self._track_event(frame)
            return frame["cue_on"] if frame["cue_on"] != was_on else None

    def set_chip_id(self, chip_id):
        with self.lock:
            self.chip_id = int(chip_id)

    @staticmethod
    def _state_name(frame):
        if frame["cue_on"]:
            return "freeze_detected"
        if frame["loco_power"] > WALK_LOCO_POWER:
            return "walking"
        if frame["total_power"] < POWER_THRESHOLD:
            return "still"
        return "moving"

    def _track_event(self, frame):
        if frame["cue_on"] and self.open_event is None:
            self.open_event = dict(id=len(self.events) + 1, start=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   first_frame=frame["n"], duration_s=0.0, peak_freeze_index=0.0, ongoing=True)
            self.events.appendleft(self.open_event)
        if self.open_event is not None:
            event = self.open_event
            event["duration_s"] = (frame["n"] - event["first_frame"] + 1) * STEP / SAMPLE_RATE_HZ
            if frame["positive"]:   # the index is meaningless in the still part of a cue's hold time
                event["peak_freeze_index"] = round(max(event["peak_freeze_index"], frame["freeze_index"]), 2)
            if not frame["cue_on"]:
                event["ongoing"] = False
                self.open_event = None

    # ---- output ------------------------------------------------------------------------------

    def state(self, since_sample=0, since_frame=0):
        """Everything the page needs: status, plus samples and frames newer than the ones it has."""
        with self.lock:
            last = self.frames[-1] if self.frames else None
            age = None if self.last_sample_time is None else time.monotonic() - self.last_sample_time
            return dict(
                status=dict(
                    receiving=age is not None and age < 2.0,
                    warming_up=last is None,
                    state=last["state"] if last else "warming_up",
                    freeze_index=round(last["freeze_index"], 2) if last else None,
                    total_power=round(last["total_power"]) if last else None,
                    armed=bool(last["armed"]) if last else False,
                    cue_on=bool(last["cue_on"]) if last else False,
                    sample_rate_hz=round(self.rate_hz, 2) if self.rate_hz else None,
                    samples=self.n_samples, lost_samples=self.lost_samples, chip_id=self.chip_id,
                    fi_threshold=FI_THRESHOLD,
                    response=next(k for k, v in RESPONSE_DEBOUNCE.items() if v == self.detector.debounce),
                ),
                recording=dict(active=self.recording is not None,
                               name=self.recording["name"] if self.recording else None,
                               rows=self.recording["rows"] if self.recording else 0, label=self.label),
                samples=[m for m in self.magnitudes if m[0] > since_sample],
                frames=[dict(n=f["n"], fi=round(f["freeze_index"], 3), power=round(f["total_power"]),
                             positive=bool(f["positive"]), cue=bool(f["cue_on"]), state=f["state"])
                        for f in self.frames if f["n"] > since_frame],
                events=[{k: v for k, v in e.items() if k != "first_frame"} for e in list(self.events)[:20]],
            )

    # ---- recording ---------------------------------------------------------------------------

    def start_recording(self, name=""):
        with self.lock:
            if self.recording:
                return dict(ok=False, error="already recording")
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:40]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{stamp}_{safe}.csv" if safe else f"{stamp}.csv"
            self.data_dir.mkdir(parents=True, exist_ok=True)
            file = open(self.data_dir / filename, "w", newline="")
            writer = csv.writer(file)
            writer.writerow(RECORDING_COLUMNS)
            self.recording = dict(name=filename, file=file, writer=writer, rows=0)
            return dict(ok=True, name=filename)

    def stop_recording(self):
        with self.lock:
            if not self.recording:
                return dict(ok=False, error="not recording")
            self.recording["file"].close()
            done = dict(ok=True, name=self.recording["name"], rows=self.recording["rows"])
            self.recording = None
            self.label = ""
            return done

    def set_response(self, response):
        with self.lock:
            if response not in RESPONSE_DEBOUNCE:
                return dict(ok=False, error=f"response must be one of {tuple(RESPONSE_DEBOUNCE)}")
            self.detector.debounce = RESPONSE_DEBOUNCE[response]
            return dict(ok=True, response=response)

    def set_label(self, label):
        with self.lock:
            if label not in LABELS and label != "":
                return dict(ok=False, error=f"label must be one of {LABELS} or empty")
            self.label = label
            return dict(ok=True, label=label)

    def list_recordings(self):
        if not self.data_dir.exists():
            return []
        files = sorted(self.data_dir.glob("*.csv"), reverse=True)
        return [dict(name=f.name, kb=round(f.stat().st_size / 1024)) for f in files]

    def recording_path(self, name):
        """Path of a finished recording, or None. Only plain file names inside data_dir are accepted."""
        path = self.data_dir / Path(name).name
        return path if path.suffix == ".csv" and path.is_file() else None


def self_test():
    """Replay the firmware test vectors through this copy of the detector."""
    vectors = Path(__file__).resolve().parents[3] / "test_vectors"
    for expected_path in sorted(vectors.glob("*_expected.csv")):
        inputs = np.loadtxt(str(expected_path).replace("_expected", "_input"), delimiter=",", skiprows=1)
        with open(expected_path) as f:
            expected = list(csv.DictReader(f))
        detector = Detector()
        got = [fr for fr in (detector.push(*row) for row in inputs) if fr]
        assert len(got) == len(expected), expected_path.name
        for g, e in zip(got, expected):
            assert int(g["cue_on"]) == int(e["cue_on"]) and int(g["positive"]) == int(e["positive"]) \
                and int(g["armed"]) == int(e["armed"]), (expected_path.name, e["sample_index"])
            assert abs(g["freeze_index"] - float(e["freeze_index"])) <= 1e-4 * max(float(e["freeze_index"]), 1e-6)
        print(f"  {expected_path.name}: {len(got)} frames match")
    print("fog_core detector matches the test vectors")


if __name__ == "__main__":
    self_test()
