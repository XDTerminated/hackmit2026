"""The device's API server: runs the detector, logs events, serves docs/api.md.

This is not a throwaway mock. It is the Linux-side server from `docs/api.md`, written so the
only thing that changes on the UNO Q is where samples come from: a SampleSource yields
(ax_mg, ay_mg, az_mg) at 64 Hz, and on the board that becomes the Bridge feed from the STM32
instead of a CSV. Everything downstream -- detector, cue state machine, event log, REST, the
live WebSocket -- is the code that ships.

On the board it is started by backend/arduino/fog_app/python/main.py through start_on_board(), which
feeds it from the Bridge (LiveSource), drives the buzzer through a cue hook, and leaves the
debug route out. FOG_DB sets where the event log lives.

`POST /debug/freeze` is the one route that is replay-only and must never exist on the board.

    uv run api/device_server.py                         replay test_vectors/walk_then_freeze
    uv run api/device_server.py --source daphnet --subject S01
    uv run api/device_server.py --seed-days 14          fill the history with demo events first
    uv run api/device_server.py --speed 20              compressed replay

Usage: python api/device_server.py [--host H] [--port P] [--source ...] [--speed N] [--seed-days N]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import os
import queue
import random
import sqlite3
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cadence import CadenceTracker  # noqa: E402
from streaming_detector import PRESETS, DetectorParams, SampleClock, StreamingDetector  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VECTOR_DIR = ROOT / "test_vectors"
CLEAN_DIR = ROOT / "data" / "daphnet" / "clean"
DB_PATH = Path(os.environ.get("FOG_DB", Path(__file__).resolve().parent / "device.sqlite3"))
logger = logging.getLogger("device_server")
DEMO_PAGE = Path(__file__).resolve().parent / "demo_page.html"   # deploy.sh ships it next to this file

FIRMWARE = "0.1.0"
SAMPLE_RATE_HZ = 64
STEP = 32  # samples per detector frame (0.5 s)
TEMPO_RANGE_BPM = (60, 140)
# Auto tempo: beats per step of the wearer's own measured cadence. The trials disagree on the best
# offset for people who freeze (Willems 2006: 10% slower; Arias & Cudeiro 2010: 10% faster), so match it.
AUTO_TEMPO_FACTOR = 1.0
CADENCE_KEY = "measured_cadence_spm"   # settings table; not a user setting

DEFAULT_SETTINGS = {
    "detection_enabled": True,
    "sensitivity": "balanced",
    "walking_gate": True,
    "cue_sound": True,
    # The prototype has no buzzer fitted: the wearer's phone plays the cue. With no app connected the
    # device falls back to its own output, which on this hardware is only the on-board LED.
    "cue_output": "phone",
    "cue_vibration": False,
    # True: the cue plays at the wearer's own walking cadence, measured on the device (cadence.py).
    # tempo_bpm is then only the fallback until enough steady walking has been seen.
    "tempo_auto": True,
    "tempo_bpm": 100,
    "cue_min_seconds": 5,
}

SETTING_RULES = {
    "detection_enabled": (bool, None),
    "sensitivity": (str, tuple(PRESETS)),
    "walking_gate": (bool, None),
    "cue_sound": (bool, None),
    "cue_output": (str, ("buzzer", "phone")),
    "cue_vibration": (bool, None),
    "tempo_auto": (bool, None),
    "tempo_bpm": (int, TEMPO_RANGE_BPM),
    "cue_min_seconds": (int, (3, 15)),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- samples


class SampleSource:
    """Yields (ax_mg, ay_mg, az_mg) forever. On the UNO Q this reads the Bridge instead."""

    name = "none"
    live = False   # True: samples arrive in real time from another thread, see LiveSource

    def samples(self) -> Iterator[tuple[float, float, float]]:
        raise NotImplementedError


class CsvReplaySource(SampleSource):
    """Loops a CSV of milli-g samples. Test vectors are real Daphnet data with known cues."""

    def __init__(self, path: Path, cols=("ax_mg", "ay_mg", "az_mg")):
        import pandas as pd   # replay only; not needed on the board

        frame = pd.read_csv(path)
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise SystemExit(f"{path.name} has no column(s) {missing}; found {list(frame.columns)}")
        self.rows = frame[list(cols)].to_numpy(dtype=float)
        self.name = path.stem

    def samples(self):
        while True:
            for row in self.rows:
                yield float(row[0]), float(row[1]), float(row[2])


class LiveSource(SampleSource):
    """Samples pushed in from another thread: on the UNO Q, the Bridge callback for the STM32.

    push() never blocks the producer; if the server falls behind, the oldest samples are dropped.
    """

    name = "bridge"
    live = True

    def __init__(self):
        self.queue: queue.Queue = queue.Queue(maxsize=SAMPLE_RATE_HZ * 10)
        self.clock = SampleClock(SAMPLE_RATE_HZ)
        self.server_thread: threading.Thread | None = None
        self.loop_ended = False   # set if Device.run() ever returns or dies

    def alive(self) -> bool:
        """False once nothing reads these samples any more (port taken, server crashed): the caller
        must then cue by other means. start_on_board() returns before the server has bound its port."""
        return self.server_thread is not None and self.server_thread.is_alive() and not self.loop_ended

    @property
    def rate_hz(self) -> float:
        return self.clock.rate_hz or float(SAMPLE_RATE_HZ)

    def push(self, t_us: int, ax_mg: float, ay_mg: float, az_mg: float) -> None:
        self.clock.tick(t_us)
        if self.queue.full():
            with contextlib.suppress(queue.Empty):
                self.queue.get_nowait()
        self.queue.put_nowait((float(ax_mg), float(ay_mg), float(az_mg)))

    def take(self, n: int, timeout_s: float) -> list | None:
        """Block until n samples are available. None if the sensor goes quiet for timeout_s."""
        block = []
        try:
            while len(block) < n:
                block.append(self.queue.get(timeout=timeout_s))
        except queue.Empty:
            return None
        return block


def build_source(args) -> SampleSource:
    if args.csv:
        return CsvReplaySource(args.csv)
    if args.source == "daphnet":
        path = CLEAN_DIR / f"{args.subject}.csv"
        if not path.exists():
            raise SystemExit(
                f"{path} not found. Run `uv run analysis/clean_daphnet.py` first, "
                f"or use --source vector."
            )
        return CsvReplaySource(path, cols=("acc_f", "acc_v", "acc_l"))
    path = VECTOR_DIR / f"{args.scenario}_input.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found.")
    return CsvReplaySource(path)


# --------------------------------------------------------------------------- storage


def connect_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start TEXT NOT NULL,
            duration_s REAL,
            trigger TEXT NOT NULL,
            peak_freeze_index REAL,
            cue_sound INTEGER, cue_vibration INTEGER, cue_output TEXT, tempo_bpm INTEGER,
            walking_resumed_s REAL,
            sensitivity TEXT,
            feedback TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    db.commit()
    return db


def load_settings(db) -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT key, value FROM settings")}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def save_settings(db, settings: dict) -> None:
    db.executemany(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, json.dumps(v)) for k, v in settings.items()],
    )
    db.commit()


def load_cadence(db) -> float | None:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (CADENCE_KEY,)).fetchone()
    return float(json.loads(row["value"])) if row else None


def event_row_to_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "start": row["start"],
        "duration_s": row["duration_s"],
        "trigger": row["trigger"],
        "peak_freeze_index": row["peak_freeze_index"],
        "cue": {
            "sound": bool(row["cue_sound"]),
            "vibration": bool(row["cue_vibration"]),
            "output": row["cue_output"],
            "tempo_bpm": row["tempo_bpm"],
        },
        "walking_resumed_s": row["walking_resumed_s"],
        "sensitivity": row["sensitivity"],
        "feedback": row["feedback"],
    }


# --------------------------------------------------------------------------- device state


@dataclass
class OpenEvent:
    id: int
    started: float             # time.monotonic(): durations must survive the app setting the clock
    peak_fi: float = 0.0
    trigger: str = "auto"
    resumed_s: float | None = None
    watching_resume: bool = False


@dataclass
class Device:
    db: sqlite3.Connection
    source: SampleSource
    speed: float = 1.0
    settings: dict = field(default_factory=dict)
    state: str = "still"
    cue_active: bool = False
    paused_until: datetime | None = None
    started_at: datetime = field(default_factory=now_utc)
    clock_offset: timedelta = timedelta(0)
    measured_rate_hz: float = float(SAMPLE_RATE_HZ)
    open_event: OpenEvent | None = None
    pause_deadline: float = 0.0        # time.monotonic() at which paused_until (shown to the wearer) runs out
    hold_until: float = 0.0            # replay only: a forced cue the detector may not end before this
    quiet_blocks: int = 0              # consecutive 2 s waits with no samples
    tasks: set = field(default_factory=set)   # keeps fire-and-forget tasks from being garbage collected
    clients: set[WebSocket] = field(default_factory=set)
    sensor_ok: bool = True
    # The cue playing right now, as the app needs it: event_id, output, tempo_bpm, trigger.
    active_cue: dict | None = None
    # Set when the wearer stops an automatic cue. The detector's own cue output stays on for its
    # hold time, so without this the next frame would start a new cue half a second later.
    wearer_stopped: bool = False
    # Called with (on, tempo_bpm) when the device's own buzzer should start or stop.
    cue_hook: Callable[[bool, int], None] | None = None
    cadence: CadenceTracker = field(default_factory=CadenceTracker)
    # What the demo page draws: the last 12 s of |acceleration| and the last 2 minutes of frames.
    recent_samples: deque = field(default_factory=lambda: deque(maxlen=SAMPLE_RATE_HZ * 12))
    recent_frames: deque = field(default_factory=lambda: deque(maxlen=240))
    n_samples: int = 0
    n_frames: int = 0
    saved_cadence: int | None = None

    def cue_tempo(self) -> int:
        """The tempo a cue starting now would play. A cue keeps the tempo it started with."""
        measured = self.cadence.cadence_spm
        if not self.settings["tempo_auto"] or measured is None:
            return int(self.settings["tempo_bpm"])
        low, high = TEMPO_RANGE_BPM
        return int(min(max(round(measured * AUTO_TEMPO_FACTOR), low), high))

    def drive_buzzer(self, on: bool, output: str = "buzzer") -> None:
        if self.cue_hook is None:
            return
        tempo = self.active_cue["tempo_bpm"] if self.active_cue else self.cue_tempo()
        with contextlib.suppress(Exception):   # a hardware hiccup must never break the event log
            self.cue_hook(on and output == "buzzer", tempo)

    # -- time -------------------------------------------------------------
    def now(self) -> datetime:
        return now_utc() + self.clock_offset

    # -- detector ---------------------------------------------------------
    def detector_params(self) -> DetectorParams:
        return DetectorParams(
            **PRESETS[self.settings["sensitivity"]],
            gate_min_walk_frames=2 if self.settings["walking_gate"] else 0,
            hold_frames=max(1, round(self.settings["cue_min_seconds"] * SAMPLE_RATE_HZ / STEP)),
        )

    def make_detector(self) -> StreamingDetector:
        return StreamingDetector(self.detector_params())

    def detection_live(self) -> bool:
        if not self.settings["detection_enabled"]:
            return False
        if self.paused_until and time.monotonic() >= self.pause_deadline:
            self.paused_until = None
        return self.paused_until is None

    def spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # -- websocket --------------------------------------------------------
    async def broadcast(self, kind: str, payload: dict) -> None:
        message = {"type": kind, "device_time": iso(self.now()), **payload}
        for socket in list(self.clients):
            try:
                await socket.send_json(message)
            except Exception:
                self.clients.discard(socket)

    def status(self) -> dict:
        return {
            "device_time": iso(self.now()),
            "sensor_ok": self.sensor_ok,
            "sample_rate_hz": round(self.measured_rate_hz, 2),
            "state": self.state,
            "cue_active": self.cue_active,
            "cue": self.active_cue,
            "cadence_spm": self.cadence.cadence_spm and round(self.cadence.cadence_spm),
            "cue_tempo_bpm": self.cue_tempo(),
            "apps_connected": len(self.clients),
            "paused_until": iso(self.paused_until) if self.paused_until else None,
            "events_today": self.count_today(),
            "uptime_s": int((now_utc() - self.started_at).total_seconds()),
            "firmware": FIRMWARE,
            "source": self.source.name,
            "replay": not self.source.live,
        }

    def count_today(self) -> int:
        midnight = self.now().replace(hour=0, minute=0, second=0, microsecond=0)
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM events WHERE start >= ?", (iso(midnight),)
        ).fetchone()
        return row["n"]

    # -- cue lifecycle ----------------------------------------------------
    async def start_cue(self, trigger: str, freeze_index: float = 0.0) -> None:
        if self.cue_active:
            return
        # cue_output "phone" needs a connected app; never leave the wearer with no cue.
        output = self.settings["cue_output"]
        if output == "phone" and not self.clients:
            output = "buzzer"
        tempo = self.cue_tempo()
        cursor = self.db.execute(
            "INSERT INTO events(start, trigger, peak_freeze_index, cue_sound, cue_vibration, "
            "cue_output, tempo_bpm, sensitivity) VALUES(?,?,?,?,?,?,?,?)",
            (
                iso(self.now()),
                trigger,
                freeze_index,
                int(self.settings["cue_sound"]),
                int(self.settings["cue_vibration"]),
                output,
                tempo,
                self.settings["sensitivity"],
            ),
        )
        self.db.commit()
        self.cue_active = True
        self.open_event = OpenEvent(id=cursor.lastrowid, started=time.monotonic(),
                                    peak_fi=freeze_index, trigger=trigger)
        self.active_cue = {"event_id": self.open_event.id, "output": output,
                           "tempo_bpm": tempo, "trigger": trigger}
        self.drive_buzzer(True, output)
        await self.broadcast("cue_started", self.active_cue)

    async def stop_cue(self, reason: str, feedback: str | None = None) -> None:
        if not self.cue_active or self.open_event is None:
            return
        event = self.open_event
        duration = max(0.5, time.monotonic() - event.started)
        self.db.execute(
            "UPDATE events SET duration_s = ?, peak_freeze_index = ?, feedback = COALESCE(?, feedback) "
            "WHERE id = ?",
            (round(duration, 1), round(event.peak_fi, 2), feedback, event.id),
        )
        self.db.commit()
        self.cue_active = False
        self.active_cue = None
        self.hold_until = 0.0
        event.watching_resume = True
        self.drive_buzzer(False)
        await self.broadcast("cue_stopped", {"event_id": event.id, "reason": reason})
        # The event stays open for up to 15 s so walking_resumed_s can be filled in.
        self.spawn(self.finalise_event(event))

    async def finalise_event(self, event: OpenEvent) -> None:
        deadline = 15.0 / max(self.speed, 1.0)
        await asyncio.sleep(deadline)
        if event.resumed_s is not None:
            self.db.execute(
                "UPDATE events SET walking_resumed_s = ? WHERE id = ?",
                (round(event.resumed_s, 1), event.id),
            )
            self.db.commit()
        event.watching_resume = False
        row = self.db.execute("SELECT * FROM events WHERE id = ?", (event.id,)).fetchone()
        if row:
            await self.broadcast("event_created", {"event": event_row_to_json(row)})

    def phone_connected(self) -> None:
        """Give a cue back to the phone it was meant for: a Wi-Fi blip must not cost the rest of the cue."""
        if (self.cue_active and self.active_cue and self.active_cue["output"] == "buzzer"
                and self.settings["cue_output"] == "phone"):
            self.active_cue["output"] = "phone"
            self.drive_buzzer(False)

    def phone_disconnected(self) -> None:
        """A cue playing on the phone must not go silent because the phone went away."""
        if self.cue_active and self.active_cue and self.active_cue["output"] == "phone" and not self.clients:
            self.active_cue["output"] = "buzzer"
            self.drive_buzzer(True, "buzzer")

    # -- the loop ---------------------------------------------------------
    async def run(self) -> None:
        detector = self.make_detector()
        sensitivity = self.settings["sensitivity"]
        gate = self.settings["walking_gate"]
        hold = self.settings["cue_min_seconds"]
        stream = None if self.source.live else self.source.samples()
        loop = asyncio.get_running_loop()
        period = (STEP / SAMPLE_RATE_HZ) / self.speed

        while True:
            tick = loop.time()

            # Settings that change the detector need it rebuilt; the wearer loses at most
            # one window of history, which is the honest cost of changing sensitivity live.
            if (self.settings["sensitivity"], self.settings["walking_gate"],
                    self.settings["cue_min_seconds"]) != (sensitivity, gate, hold):
                detector = self.make_detector()
                sensitivity = self.settings["sensitivity"]
                gate = self.settings["walking_gate"]
                hold = self.settings["cue_min_seconds"]

            if self.source.live:
                # Wait for the sensor in a worker thread so REST and the WebSocket stay responsive.
                block = await loop.run_in_executor(None, self.source.take, STEP, 2.0)
                if (block is not None) != self.sensor_ok:
                    self.sensor_ok = block is not None
                    await self.broadcast("status", self.status())
                if block is None:
                    # No samples, no detector frames: nothing else would ever end this cue.
                    self.quiet_blocks += 1
                    if self.cue_active and self.open_event.trigger == "auto" and self.quiet_blocks >= 2:
                        await self.stop_cue("sensor_lost")
                    continue
                self.quiet_blocks = 0
                self.measured_rate_hz = self.source.rate_hz
            else:
                block = [next(stream) for _ in range(STEP)]

            frame = None
            for ax, ay, az in block:
                magnitude = math.sqrt(ax * ax + ay * ay + az * az)
                self.cadence.push(magnitude)
                self.n_samples += 1
                self.recent_samples.append((self.n_samples, round(magnitude)))
                got = detector.push_magnitude(magnitude)
                if got is not None:
                    frame = got

            if frame is not None:
                try:
                    await self.on_frame(frame)
                except Exception:   # noqa: BLE001 - one bad frame must not end detection for good
                    logger.exception("frame handling failed")

            if not self.source.live:   # a live sensor paces the loop by itself
                elapsed = loop.time() - tick
                await asyncio.sleep(max(0.0, period - elapsed))

    def track_cadence(self, frame) -> None:
        """Measure the wearer's cadence while they walk well; remember it across restarts."""
        if self.cadence.on_frame(frame, self.cue_active) is None:
            return
        measured = self.cadence.cadence_spm
        if measured is not None and round(measured) != self.saved_cadence:
            self.saved_cadence = round(measured)
            save_settings(self.db, {CADENCE_KEY: self.saved_cadence})

    async def on_frame(self, frame) -> None:
        walking = frame.loco_power > DetectorParams().walk_loco_power
        previous_state = self.state
        try:
            self.track_cadence(frame)
        except Exception:   # noqa: BLE001 - the tempo is a nicety; the cue is not
            logger.exception("cadence tracking failed")

        # Walking again: walking-level rhythm with the freeze index back under its line. Watched from the
        # start of the cue (the wearer is meant to walk off while it plays) until 15 s after it ends.
        event = self.open_event
        if event and (self.cue_active or event.watching_resume) and event.resumed_s is None:
            if walking and frame.freeze_index < DetectorParams().fi_threshold:
                event.resumed_s = time.monotonic() - event.started

        if not self.detection_live():
            # Switched off or paused in the middle of an automatic cue: nothing below would ever end it.
            if self.cue_active and self.open_event.trigger == "auto":
                await self.stop_cue("paused")
            self.state = "walking" if walking else "still"
        elif self.cue_active and self.open_event and self.open_event.trigger == "manual":
            self.state = "walking" if walking else "still"
        else:
            if not frame.cue_on:
                self.wearer_stopped = False
            if frame.cue_on and not self.cue_active and not self.wearer_stopped:
                await self.start_cue("auto", frame.freeze_index)
            elif (not frame.cue_on and self.cue_active and self.open_event.trigger == "auto"
                  and time.monotonic() >= self.hold_until):
                await self.stop_cue("finished")
            self.state = "freeze_detected" if self.cue_active else ("walking" if walking else "still")

        # Only positive frames: in the still part of a cue's hold the index is a ratio of two near-zeros.
        if self.open_event and self.cue_active and frame.positive:
            self.open_event.peak_fi = max(self.open_event.peak_fi, frame.freeze_index)

        self.n_frames += 1
        self.recent_frames.append(dict(
            n=self.n_frames, freeze_index=round(frame.freeze_index, 3), loco_power=round(frame.loco_power),
            freeze_power=round(frame.total_power - frame.loco_power), positive=bool(frame.positive),
            stopping=bool(frame.stopping), armed=bool(frame.armed), cue=self.cue_active, state=self.state))

        if self.state != previous_state or self.cue_active:
            await self.broadcast("status", self.status())


# --------------------------------------------------------------------------- demo history


def seed_history(db, days: int, settings: dict) -> None:
    """Fill the log with plausible past events so the history screen has something to draw.

    Rates come from the measured numbers in docs/api.md (Daphnet, balanced preset): roughly
    47 false cues/hour against ~90% of episodes caught. This is demo data, not evidence --
    it is generated, and the writeup must say so.
    """
    existing = db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    if existing:
        return
    rng = random.Random(20260919)
    today = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for day in range(days, 0, -1):
        date = today - timedelta(days=day)
        for _ in range(rng.randint(3, 14)):
            hour = rng.choices([8, 9, 10, 12, 14, 16, 17, 19, 20], k=1)[0]
            start = date + timedelta(hours=hour, minutes=rng.randint(0, 59),
                                     seconds=rng.randint(0, 59))
            trigger = "manual" if rng.random() < 0.12 else "auto"
            feedback = "false_alarm" if trigger == "auto" and rng.random() < 0.28 else None
            resumed = None if rng.random() < 0.25 else round(rng.uniform(1.5, 9.0), 1)
            rows.append((
                iso(start), round(rng.uniform(5.0, 22.0), 1), trigger,
                round(rng.uniform(1.1, 6.5), 2), 1, 0, settings["cue_output"],
                settings["tempo_bpm"], resumed, settings["sensitivity"], feedback,
            ))
    rows.sort(key=lambda r: r[0])
    db.executemany(
        "INSERT INTO events(start, duration_s, trigger, peak_freeze_index, cue_sound, "
        "cue_vibration, cue_output, tempo_bpm, walking_resumed_s, sensitivity, feedback) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    db.commit()
    print(f"seeded {len(rows)} demo events over {days} days")


# --------------------------------------------------------------------------- app


def create_app(device: Device, debug_routes: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        loop_task = asyncio.create_task(device.run())

        def loop_ended(task):
            if isinstance(device.source, LiveSource):
                device.source.loop_ended = True
            if not task.cancelled() and task.exception():
                logger.error("the detector loop died: %r", task.exception())

        loop_task.add_done_callback(loop_ended)
        yield
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    app = FastAPI(title="FoG device API", version=FIRMWARE, lifespan=lifespan)
    if debug_routes:
        # Laptop replay only: lets a browser tool on another origin read this server. On the board the API
        # has no authentication (docs/api.md) and sends no CORS headers, so a web page on the same network
        # cannot read it or change settings. That is not protection: bodiless POSTs (/cue/stop, /resume)
        # and the WebSocket are not subject to CORS. The native app is not a browser and needs none.
        app.add_middleware(
            CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
        )
    api = "/api/v1"


    # -- settings ---------------------------------------------------------
    @app.get(api + "/settings")
    def get_settings():
        return device.settings

    @app.patch(api + "/settings")
    async def patch_settings(patch: dict = Body(...)):
        candidate = dict(device.settings)
        for key, value in patch.items():
            if key not in SETTING_RULES:
                raise HTTPException(400, f"unknown setting '{key}'")
            kind, allowed = SETTING_RULES[key]
            if kind is bool and not isinstance(value, bool):
                raise HTTPException(400, f"'{key}' must be a boolean")
            if kind is int:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise HTTPException(400, f"'{key}' must be an integer")
                low, high = allowed
                if not low <= value <= high:
                    raise HTTPException(400, f"'{key}' must be between {low} and {high}")
            if kind is str and value not in allowed:
                raise HTTPException(400, f"'{key}' must be one of {list(allowed)}")
            candidate[key] = value
        if candidate["detection_enabled"] and not (candidate["cue_sound"] or candidate["cue_vibration"]):
            raise HTTPException(400, "at least one of cue_sound / cue_vibration must stay on")
        device.settings = candidate
        save_settings(device.db, candidate)
        await device.broadcast("status", device.status())
        return device.settings

    def whole_number(body: dict, key: str, default: int, low: int, high: int) -> int:
        value = body.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise HTTPException(400, f"{key} must be a whole number between {low} and {high}")
        return value

    # -- status -----------------------------------------------------------
    @app.get(api + "/status")
    def get_status():
        return device.status()

    @app.post(api + "/time")
    def set_time(body: dict = Body(...)):
        raw = body.get("now")
        if not isinstance(raw, str) or not raw:
            raise HTTPException(400, "body must be {\"now\": \"<ISO time>\"}")
        try:
            target = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"could not parse '{raw}' as an ISO time") from None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        device.clock_offset = target - now_utc()
        return {"device_time": iso(device.now())}

    # -- actions ----------------------------------------------------------
    @app.post(api + "/cue/start")
    async def cue_start(body: dict = Body(default={})):
        seconds = whole_number(body, "seconds", 10, 3, 60)
        if device.cue_active:   # one cue at a time; the one that is playing stays as it is
            return device.status()
        await device.start_cue("manual")
        event_id = device.open_event.id

        async def auto_stop():
            await asyncio.sleep(seconds)
            # Only this beat: the wearer may have stopped it and asked for another since.
            if device.cue_active and device.open_event.id == event_id:
                await device.stop_cue("finished")

        device.spawn(auto_stop())
        return device.status()

    @app.post(api + "/cue/stop")
    async def cue_stop(body: dict = Body(default={})):
        # The app's STOP button also marks the event a false alarm; docs/api.md.
        feedback = body.get("feedback")
        if feedback not in (None, "real", "false_alarm"):
            raise HTTPException(400, "feedback must be 'real' or 'false_alarm'")
        # Only a cue that is actually playing can be stopped and judged. open_event lingers after a
        # cue ends, so answering with its id here would let the app mark an older event by mistake.
        if not device.cue_active:
            return {"stopped": False, "event_id": None}
        event = device.open_event
        if event.trigger == "auto":   # stopping a beat the wearer asked for must not release an earlier latch
            device.wearer_stopped = True
        await device.stop_cue("stopped_by_user", feedback)
        return {"stopped": True, "event_id": event.id}

    @app.post(api + "/cue/test")
    async def cue_test():
        if device.cue_active:   # a test must never interrupt, or later silence, a cue that is really playing
            return {"testing": False, "seconds": 0}
        await device.broadcast(
            "cue_started",
            {"event_id": None, "output": device.settings["cue_output"],
             "tempo_bpm": device.cue_tempo(), "trigger": "test"},
        )
        device.drive_buzzer(True, device.settings["cue_output"])

        async def end():
            await asyncio.sleep(2)
            if not device.cue_active:   # a real cue that started meanwhile keeps the buzzer
                device.drive_buzzer(False)
            await device.broadcast("cue_stopped", {"event_id": None, "reason": "finished"})

        device.spawn(end())
        return {"testing": True, "seconds": 2}

    @app.post(api + "/pause")
    async def pause(body: dict = Body(...)):
        minutes = whole_number(body, "minutes", 15, 1, 240)
        device.paused_until = device.now() + timedelta(minutes=minutes)
        device.pause_deadline = time.monotonic() + minutes * 60
        if device.cue_active and device.open_event.trigger == "auto":   # a beat the wearer asked for plays on
            await device.stop_cue("paused")
        await device.broadcast("status", device.status())
        return device.status()

    @app.post(api + "/resume")
    async def resume():
        device.paused_until = None
        await device.broadcast("status", device.status())
        return device.status()

    # -- events -----------------------------------------------------------
    @app.get(api + "/events")
    def get_events(since: str | None = None, limit: int = 100):
        limit = max(1, min(limit, 500))
        if since:
            rows = device.db.execute(
                "SELECT * FROM events WHERE start >= ? ORDER BY start DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        else:
            rows = device.db.execute(
                "SELECT * FROM events ORDER BY start DESC LIMIT ?", (limit,)
            ).fetchall()
        return {"events": [event_row_to_json(r) for r in rows]}

    @app.patch(api + "/events/{event_id}")
    def patch_event(event_id: int, body: dict = Body(...)):
        feedback = body.get("feedback")
        if feedback not in (None, "real", "false_alarm"):
            raise HTTPException(400, "feedback must be null, 'real' or 'false_alarm'")
        row = device.db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"no event {event_id}")
        device.db.execute("UPDATE events SET feedback = ? WHERE id = ?", (feedback, event_id))
        device.db.commit()
        row = device.db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return event_row_to_json(row)

    @app.get(api + "/events/summary")
    def events_summary(days: int = 14):
        days = max(1, min(days, 90))
        start = (device.now() - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = device.db.execute(
            "SELECT * FROM events WHERE start >= ? ORDER BY start", (iso(start),)
        ).fetchall()
        buckets = {
            iso(start + timedelta(days=d))[:10]: {
                "date": iso(start + timedelta(days=d))[:10],
                "auto": 0, "manual": 0, "false_alarm": 0,
                "mean_duration_s": 0.0, "resumed": 0, "with_outcome": 0,
            }
            for d in range(days)
        }
        durations: dict[str, list[float]] = {key: [] for key in buckets}
        for row in rows:
            key = row["start"][:10]
            if key not in buckets:
                continue
            bucket = buckets[key]
            if row["feedback"] == "false_alarm":
                bucket["false_alarm"] += 1
            elif row["trigger"] == "manual":
                bucket["manual"] += 1
            else:
                bucket["auto"] += 1
            if row["duration_s"]:
                durations[key].append(row["duration_s"])
            if row["feedback"] != "false_alarm":
                bucket["with_outcome"] += 1
                if row["walking_resumed_s"] is not None:
                    bucket["resumed"] += 1
        for key, bucket in buckets.items():
            values = durations[key]
            bucket["mean_duration_s"] = round(float(np.mean(values)), 1) if values else 0.0
        days_list = list(buckets.values())
        total_outcome = sum(b["with_outcome"] for b in days_list)
        total_resumed = sum(b["resumed"] for b in days_list)
        return {
            "days": days_list,
            "walking_resumed_rate": round(total_resumed / total_outcome, 3) if total_outcome else None,
        }

    # -- demo page --------------------------------------------------------
    # Read-only, and polled over REST on purpose: a WebSocket client counts as a connected app, and a
    # projector page must never make the device believe a phone is there to play the cue.
    @app.get(api + "/frames")
    def get_frames(since_frame: int = 0, since_sample: int = 0):
        params = device.detector_params()
        return {
            "status": device.status(),
            "thresholds": {"freeze_index": params.fi_threshold, "band_power": params.power_threshold,
                           "walking_power": params.walk_loco_power},
            # The page starts over when these run behind what it has: the server was restarted.
            "n_frames": device.n_frames,
            "n_samples": device.n_samples,
            "frames": [f for f in list(device.recent_frames) if f["n"] > since_frame],
            "samples": [s for s in list(device.recent_samples) if s[0] > since_sample],
        }

    @app.get("/demo")
    def demo_page():
        if not DEMO_PAGE.exists():
            raise HTTPException(404, "demo_page.html was not deployed next to device_server.py")
        return FileResponse(DEMO_PAGE, media_type="text/html")

    # -- replay only ------------------------------------------------------
    async def debug_freeze():
        """Replay-only. Must never exist on the board: it would show a cue the detector
        never produced, and nobody watching could tell the difference."""
        await device.start_cue("auto", freeze_index=3.4)
        # The detector knows nothing of this cue and would end it on its next frame: hold it, then let go.
        device.hold_until = time.monotonic() + device.settings["cue_min_seconds"]
        return {"forced": True}

    if debug_routes:
        app.post(api + "/debug/freeze")(debug_freeze)

    # -- live channel -----------------------------------------------------
    @app.websocket(api + "/live")
    async def live(socket: WebSocket):
        await socket.accept()
        device.clients.add(socket)
        device.phone_connected()
        try:
            await socket.send_json(
                {"type": "status", "device_time": iso(device.now()), **device.status()}
            )
            while True:
                try:
                    await asyncio.wait_for(socket.receive_text(), timeout=5.0)
                except asyncio.TimeoutError:
                    await socket.send_json(
                        {"type": "status", "device_time": iso(device.now()), **device.status()}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            device.clients.discard(socket)
            device.phone_disconnected()

    return app


def start_on_board(cue_hook: Callable[[bool, int], None] | None = None, port: int = 8000) -> LiveSource:
    """Run the server in a background thread, fed by the returned LiveSource. No debug route."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = connect_db()
    settings = load_settings(db)
    save_settings(db, settings)
    source = LiveSource()
    device = Device(db=db, source=source, settings=settings, cue_hook=cue_hook,
                    cadence=CadenceTracker(initial_spm=load_cadence(db)))
    # A phone that drops off the network says no goodbye. Pinging every 3 s notices within ~6 s, so its cue
    # moves to the device's own output; the default (20 s + 20 s) leaves a cue playing to nobody.
    config = uvicorn.Config(create_app(device, debug_routes=False), host="0.0.0.0", port=port, log_level="warning",
                            ws_ping_interval=3, ws_ping_timeout=3)
    source.server_thread = threading.Thread(target=uvicorn.Server(config).run, daemon=True, name="device-server")
    source.server_thread.start()
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--source", choices=["vector", "daphnet"], default="vector")
    parser.add_argument("--csv", type=Path, help="replay this recording instead (columns ax_mg, ay_mg, az_mg)")
    parser.add_argument("--scenario", default="walk_then_freeze",
                        help="test vector to loop when --source vector")
    parser.add_argument("--subject", default="S01", help="Daphnet subject when --source daphnet")
    parser.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    parser.add_argument("--seed-days", type=int, default=0,
                        help="generate this many days of demo history if the log is empty")
    parser.add_argument("--fresh", action="store_true", help="delete the event log first")
    args = parser.parse_args()

    if args.fresh and DB_PATH.exists():
        DB_PATH.unlink()

    db = connect_db()
    settings = load_settings(db)
    save_settings(db, settings)
    if args.seed_days:
        seed_history(db, args.seed_days, settings)

    device = Device(db=db, source=build_source(args), speed=args.speed, settings=settings)
    print(f"source={device.source.name} speed={args.speed}x  http://{args.host}:{args.port}/api/v1")
    uvicorn.run(create_app(device), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
