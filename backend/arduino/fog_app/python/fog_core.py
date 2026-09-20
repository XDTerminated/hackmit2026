"""Core of the diagnostics page: live state, detected events and labelled recording.

No Arduino imports, so the same code runs on the UNO Q (from main.py) and on a laptop (from
../dev_server.py). The detector is backend/api/streaming_detector.py, the project's one
implementation: deploy.sh copies it next to this file on the board, and on a laptop it is
imported from the repo.
"""

import csv
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    from streaming_detector import DetectorParams, SampleClock, StreamingDetector
except ImportError:   # running from the repo rather than from the deployed app folder
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "api"))
    from streaming_detector import DetectorParams, SampleClock, StreamingDetector

PARAMS = DetectorParams()
SAMPLE_RATE_HZ = PARAMS.sample_rate_hz
SAMPLE_PERIOD_US = 1_000_000 / SAMPLE_RATE_HZ
FRAME_SECONDS = PARAMS.step / SAMPLE_RATE_HZ

LABELS = ("walking", "standing", "freezing")
RECORDING_COLUMNS = ["t_us", "ax_mg", "ay_mg", "az_mg", "gx_dps", "gy_dps", "gz_dps", "label"]


def state_name(frame):
    if frame.cue_on:
        return "freeze_detected"
    if frame.loco_power > PARAMS.walk_loco_power:
        return "walking"
    if frame.total_power < PARAMS.power_threshold:
        return "still"
    return "moving"


class FogCore:
    """Thread-safe hub: samples come in from the Bridge thread, the web server reads state out."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.lock = threading.Lock()
        self.detector = StreamingDetector(PARAMS)
        self.clock = SampleClock(SAMPLE_RATE_HZ)
        self.magnitudes = deque(maxlen=SAMPLE_RATE_HZ * 15)   # (sample number, |acc| mg)
        self.frames = deque(maxlen=240)                       # 2 minutes of (frame number, Frame, state)
        self.events = deque(maxlen=200)
        self.open_event = None
        self.n_samples = 0
        self.last_sample_time = None
        self.chip_id = None
        self.recording = None        # dict(name, file, writer, rows) while recording
        self.label = ""

    # ---- input -------------------------------------------------------------------------------

    def add_sample(self, t_us, ax, ay, az, gx, gy, gz):
        """Feed one IMU sample. Returns True/False when the cue should switch on/off, else None."""
        with self.lock:
            self.clock.tick(t_us)
            self.last_sample_time = time.monotonic()
            self.n_samples += 1

            if self.recording:
                self.recording["writer"].writerow(
                    [int(t_us), f"{ax:.1f}", f"{ay:.1f}", f"{az:.1f}", f"{gx:.1f}", f"{gy:.1f}", f"{gz:.1f}", self.label])
                self.recording["rows"] += 1

            was_on = self.detector.cue_on
            frame = self.detector.push(ax, ay, az)
            newest = self.detector.buffer[self.detector.head - 1]   # the magnitude push() just stored
            self.magnitudes.append((self.n_samples, round(float(newest), 1)))
            if frame is None:
                return None

            self.frames.append((self.detector.n_frames, frame, state_name(frame)))
            self._track_event(self.detector.n_frames, frame)
            return frame.cue_on if frame.cue_on != was_on else None

    def set_chip_id(self, chip_id):
        with self.lock:
            self.chip_id = int(chip_id)

    def _track_event(self, n, frame):
        if frame.cue_on and self.open_event is None:
            self.open_event = dict(id=len(self.events) + 1, start=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   first_frame=n, duration_s=0.0, peak_freeze_index=0.0, ongoing=True)
            self.events.appendleft(self.open_event)
        if self.open_event is not None:
            event = self.open_event
            event["duration_s"] = (n - event["first_frame"] + 1) * FRAME_SECONDS
            if frame.positive:   # the index is meaningless in the still part of a cue's hold time
                event["peak_freeze_index"] = round(max(event["peak_freeze_index"], frame.freeze_index), 2)
            if not frame.cue_on:
                event["ongoing"] = False
                self.open_event = None

    # ---- output ------------------------------------------------------------------------------

    def state(self, since_sample=0, since_frame=0):
        """Everything the page needs: status, plus samples and frames newer than the ones it has."""
        with self.lock:
            last, last_state = (self.frames[-1][1], self.frames[-1][2]) if self.frames else (None, "warming_up")
            age = None if self.last_sample_time is None else time.monotonic() - self.last_sample_time
            return dict(
                status=dict(
                    receiving=age is not None and age < 2.0,
                    state=last_state,
                    freeze_index=round(last.freeze_index, 2) if last else None,
                    total_power=round(last.total_power) if last else None,
                    armed=bool(last.armed) if last else False,
                    sample_rate_hz=round(self.clock.rate_hz, 2) if self.clock.rate_hz else None,
                    samples=self.n_samples, lost_samples=self.clock.lost, chip_id=self.chip_id,
                    fi_threshold=PARAMS.fi_threshold, power_threshold=PARAMS.power_threshold,
                ),
                recording=dict(active=self.recording is not None,
                               name=self.recording["name"] if self.recording else None,
                               rows=self.recording["rows"] if self.recording else 0, label=self.label),
                samples=[m for m in self.magnitudes if m[0] > since_sample],
                frames=[dict(n=n, fi=round(f.freeze_index, 3), power=round(f.total_power), cue=bool(f.cue_on), state=state)
                        for n, f, state in self.frames if n > since_frame],
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
