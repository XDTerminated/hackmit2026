"""The device's API server: runs the detector, logs events, serves docs/api.md.

This is not a throwaway mock. It is the Linux-side server from `docs/api.md`, written so the
only thing that changes on the UNO Q is where samples come from: a SampleSource yields
(ax_mg, ay_mg, az_mg) at 64 Hz, and on the board that becomes the Bridge feed from the STM32
instead of a CSV. Everything downstream -- detector, cue state machine, event log, REST, the
live WebSocket -- is the code that ships.

On the board it is started by device/fog_app/python/main.py through start_on_board(), which
feeds it from the Bridge (LiveSource), drives the buzzer through a cue hook, and leaves the
debug route out. FOG_DB sets where the event log lives.

`POST /debug/freeze` is the one route that is replay-only and must never exist on the board.

    uv run src/device_server.py                         replay test_vectors/walk_then_freeze
    uv run src/device_server.py --source daphnet --subject S01
    uv run src/device_server.py --seed-days 14          fill the history with demo events first
    uv run src/device_server.py --speed 20              compressed replay

Usage: python src/device_server.py [--host H] [--port P] [--source ...] [--speed N] [--seed-days N]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import queue
import random
import sqlite3
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent))
from streaming_detector import DetectorParams, StreamingDetector  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VECTOR_DIR = ROOT / "test_vectors"
CLEAN_DIR = ROOT / "data" / "daphnet" / "clean"
DB_PATH = Path(os.environ.get("FOG_DB", ROOT / "analysis" / "device.sqlite3"))

FIRMWARE = "0.1.0"
SAMPLE_RATE_HZ = 64
STEP = 32  # samples per detector frame (0.5 s)

# docs/api.md: sensitivity presets. The thresholds live here, never in the app.
PRESETS = {
    "catch_more": dict(fi_threshold=1.056, power_threshold=178.0, debounce_frames=1),
    "balanced": dict(fi_threshold=1.056, power_threshold=178.0, debounce_frames=2),
    "fewer_alerts": dict(fi_threshold=1.656, power_threshold=13_335.0, debounce_frames=2),
}

DEFAULT_SETTINGS = {
    "detection_enabled": True,
    "sensitivity": "balanced",
    "walking_gate": True,
    "cue_sound": True,
    "cue_output": "buzzer",
    "cue_vibration": False,
    "tempo_bpm": 100,
    "volume": 70,
    "cue_min_seconds": 5,
    "log_events": True,
}

SETTING_RULES = {
    "detection_enabled": (bool, None),
    "sensitivity": (str, tuple(PRESETS)),
    "walking_gate": (bool, None),
    "cue_sound": (bool, None),
    "cue_output": (str, ("buzzer", "phone")),
    "cue_vibration": (bool, None),
    "tempo_bpm": (int, (60, 140)),
    "volume": (int, (0, 100)),
    "cue_min_seconds": (int, (3, 15)),
    "log_events": (bool, None),
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
        self.rate_hz = float(SAMPLE_RATE_HZ)
        self._last_t_us: int | None = None
        self._device_time_us = 0
        self._recent: deque = deque(maxlen=SAMPLE_RATE_HZ * 10 + 1)

    def push(self, t_us: int, ax_mg: float, ay_mg: float, az_mg: float) -> None:
        t_us = int(t_us)
        if self._last_t_us is not None:
            self._device_time_us += (t_us - self._last_t_us) % 2**32   # micros() wraps every ~71 min
            self._recent.append(self._device_time_us)
            if len(self._recent) > SAMPLE_RATE_HZ:
                span = self._recent[-1] - self._recent[0]
                if span:
                    self.rate_hz = (len(self._recent) - 1) * 1_000_000 / span
        self._last_t_us = t_us
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
    if args.source == "daphnet":
        path = CLEAN_DIR / f"{args.subject}.csv"
        if not path.exists():
            raise SystemExit(
                f"{path} not found. Run `uv run src/clean_daphnet.py` first, "
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
    started: datetime
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
    manual_until: datetime | None = None
    clients: set[WebSocket] = field(default_factory=set)
    sensor_ok: bool = True
    # Called with (on, tempo_bpm) when the device's own buzzer should start or stop.
    cue_hook: Callable[[bool, int], None] | None = None

    def drive_buzzer(self, on: bool, output: str = "buzzer") -> None:
        if self.cue_hook is None:
            return
        with contextlib.suppress(Exception):   # a hardware hiccup must never break the event log
            self.cue_hook(on and output == "buzzer", int(self.settings["tempo_bpm"]))

    # -- time -------------------------------------------------------------
    def now(self) -> datetime:
        return now_utc() + self.clock_offset

    # -- detector ---------------------------------------------------------
    def make_detector(self) -> StreamingDetector:
        preset = PRESETS[self.settings["sensitivity"]]
        params = DetectorParams(
            fi_threshold=preset["fi_threshold"],
            power_threshold=preset["power_threshold"],
            debounce_frames=preset["debounce_frames"],
            gate_min_walk_frames=2 if self.settings["walking_gate"] else 0,
            hold_frames=max(1, round(self.settings["cue_min_seconds"] * 2)),
        )
        return StreamingDetector(params)

    def detection_live(self) -> bool:
        if not self.settings["detection_enabled"]:
            return False
        return not (self.paused_until and self.now() < self.paused_until)

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
            "paused_until": iso(self.paused_until) if self.paused_until else None,
            "events_today": self.count_today(),
            "uptime_s": int((now_utc() - self.started_at).total_seconds()),
            "firmware": FIRMWARE,
            "source": self.source.name,
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
                self.settings["tempo_bpm"],
                self.settings["sensitivity"],
            ),
        )
        self.db.commit()
        self.cue_active = True
        self.open_event = OpenEvent(id=cursor.lastrowid, started=self.now(),
                                    peak_fi=freeze_index, trigger=trigger)
        self.drive_buzzer(True, output)
        await self.broadcast(
            "cue_started",
            {
                "event_id": self.open_event.id,
                "output": output,
                "tempo_bpm": self.settings["tempo_bpm"],
                "trigger": trigger,
            },
        )

    async def stop_cue(self, reason: str, feedback: str | None = None) -> None:
        if not self.cue_active or self.open_event is None:
            return
        event = self.open_event
        duration = max(0.5, (self.now() - event.started).total_seconds())
        self.db.execute(
            "UPDATE events SET duration_s = ?, peak_freeze_index = ?, feedback = COALESCE(?, feedback) "
            "WHERE id = ?",
            (round(duration, 1), round(event.peak_fi, 2), feedback, event.id),
        )
        self.db.commit()
        self.cue_active = False
        self.manual_until = None
        event.watching_resume = True
        self.drive_buzzer(False)
        await self.broadcast("cue_stopped", {"event_id": event.id, "reason": reason})
        # The event stays open for up to 15 s so walking_resumed_s can be filled in.
        asyncio.create_task(self.finalise_event(event))

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

    # -- the loop ---------------------------------------------------------
    async def run(self) -> None:
        detector = self.make_detector()
        sensitivity = self.settings["sensitivity"]
        gate = self.settings["walking_gate"]
        hold = self.settings["cue_min_seconds"]
        stream = None if self.source.live else self.source.samples()
        period = (STEP / SAMPLE_RATE_HZ) / self.speed
        pending_resume: list[OpenEvent] = []

        while True:
            tick = asyncio.get_event_loop().time()

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
                block = await asyncio.get_event_loop().run_in_executor(None, self.source.take, STEP, 2.0)
                if (block is not None) != self.sensor_ok:
                    self.sensor_ok = block is not None
                    await self.broadcast("status", self.status())
                if block is None:
                    continue
                self.measured_rate_hz = self.source.rate_hz
            else:
                block = [next(stream) for _ in range(STEP)]

            frame = None
            for ax, ay, az in block:
                got = detector.push(ax, ay, az)
                if got is not None:
                    frame = got

            if frame is not None:
                await self.on_frame(frame, pending_resume)

            if not self.source.live:   # a live sensor paces the loop by itself
                elapsed = asyncio.get_event_loop().time() - tick
                await asyncio.sleep(max(0.0, period - elapsed))

    async def on_frame(self, frame, pending_resume) -> None:
        walking = frame.loco_power > DetectorParams().walk_loco_power
        previous_state = self.state

        if self.open_event and self.open_event.watching_resume and walking:
            if self.open_event.resumed_s is None:
                self.open_event.resumed_s = (self.now() - self.open_event.started).total_seconds()

        if not self.detection_live():
            self.state = "walking" if walking else "still"
        elif self.cue_active and self.open_event and self.open_event.trigger == "manual":
            self.state = "walking" if walking else "still"
        else:
            if frame.cue_on and not self.cue_active:
                await self.start_cue("auto", frame.freeze_index)
            elif not frame.cue_on and self.cue_active and self.open_event.trigger == "auto":
                await self.stop_cue("finished")
            self.state = "freeze_detected" if self.cue_active else ("walking" if walking else "still")

        if self.open_event and self.cue_active:
            self.open_event.peak_fi = max(self.open_event.peak_fi, frame.freeze_index)

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
    app = FastAPI(title="FoG device API", version=FIRMWARE)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    api = "/api/v1"

    @app.on_event("startup")
    async def _start():
        app.state.loop_task = asyncio.create_task(device.run())

    @app.on_event("shutdown")
    async def _stop():
        app.state.loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.loop_task

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

    # -- status -----------------------------------------------------------
    @app.get(api + "/status")
    def get_status():
        return device.status()

    @app.post(api + "/time")
    def set_time(body: dict = Body(...)):
        raw = body.get("now")
        if not raw:
            raise HTTPException(400, "body must be {\"now\": \"<ISO time>\"}")
        try:
            target = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"could not parse '{raw}' as an ISO time")
        device.clock_offset = target - now_utc()
        return {"device_time": iso(device.now())}

    # -- actions ----------------------------------------------------------
    @app.post(api + "/cue/start")
    async def cue_start(body: dict = Body(default={})):
        seconds = int(body.get("seconds", 10))
        if not 3 <= seconds <= 60:
            raise HTTPException(400, "seconds must be between 3 and 60")
        await device.start_cue("manual")
        device.manual_until = device.now() + timedelta(seconds=seconds)

        async def auto_stop():
            await asyncio.sleep(seconds)
            if device.cue_active and device.open_event and device.open_event.trigger == "manual":
                await device.stop_cue("finished")

        asyncio.create_task(auto_stop())
        return device.status()

    @app.post(api + "/cue/stop")
    async def cue_stop(body: dict = Body(default={})):
        # The app's STOP button also marks the event a false alarm; docs/api.md.
        feedback = body.get("feedback")
        if feedback not in (None, "real", "false_alarm"):
            raise HTTPException(400, "feedback must be 'real' or 'false_alarm'")
        event_id = device.open_event.id if device.open_event else None
        await device.stop_cue("stopped_by_user", feedback)
        return {"stopped": True, "event_id": event_id}

    @app.post(api + "/cue/test")
    async def cue_test():
        await device.broadcast(
            "cue_started",
            {"event_id": None, "output": device.settings["cue_output"],
             "tempo_bpm": device.settings["tempo_bpm"], "trigger": "test"},
        )
        device.drive_buzzer(True, device.settings["cue_output"])

        async def end():
            await asyncio.sleep(2)
            if not device.cue_active:   # a real cue that started meanwhile keeps the buzzer
                device.drive_buzzer(False)
            await device.broadcast("cue_stopped", {"event_id": None, "reason": "finished"})

        asyncio.create_task(end())
        return {"testing": True, "seconds": 2}

    @app.post(api + "/pause")
    async def pause(body: dict = Body(...)):
        minutes = int(body.get("minutes", 15))
        if not 1 <= minutes <= 240:
            raise HTTPException(400, "minutes must be between 1 and 240")
        device.paused_until = device.now() + timedelta(minutes=minutes)
        if device.cue_active:
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

    # -- replay only ------------------------------------------------------
    async def debug_freeze():
        """Replay-only. Must never exist on the board: it would show a cue the detector
        never produced, and nobody watching could tell the difference."""
        await device.start_cue("auto", freeze_index=3.4)

        async def end():
            await asyncio.sleep(device.settings["cue_min_seconds"])
            if device.cue_active:
                await device.stop_cue("finished")

        asyncio.create_task(end())
        return {"forced": True}

    if debug_routes:
        app.post(api + "/debug/freeze")(debug_freeze)

    # -- live channel -----------------------------------------------------
    @app.websocket(api + "/live")
    async def live(socket: WebSocket):
        await socket.accept()
        device.clients.add(socket)
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

    return app


def start_on_board(cue_hook: Callable[[bool, int], None] | None = None, port: int = 8000) -> LiveSource:
    """Run the server in a background thread, fed by the returned LiveSource. No debug route."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = connect_db()
    settings = load_settings(db)
    save_settings(db, settings)
    source = LiveSource()
    device = Device(db=db, source=source, settings=settings, cue_hook=cue_hook)
    config = uvicorn.Config(create_app(device, debug_routes=False), host="0.0.0.0", port=port, log_level="warning")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True, name="device-server").start()
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--source", choices=["vector", "daphnet"], default="vector")
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
