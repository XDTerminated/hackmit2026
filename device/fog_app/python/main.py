# Linux side of the Freezing of Gait Monitor app on the Arduino UNO Q.
#
# Receives IMU samples from the sketch over the Bridge and feeds two things:
#
#   port 8000  the device API from docs/api.md (analysis/src/device_server.py): detector, settings,
#              SQLite event log, REST + WebSocket. This is what the phone app talks to, and it owns
#              the cue: it decides when the buzzer plays.
#   port 7000  the diagnostics page in ../assets (fog_core.py): live charts, sample-rate check and
#              labelled recording. It never drives the cue while the device API is running.
#
# device_server.py and streaming_detector.py are copied next to this file by ../deploy.sh. If the
# device API cannot start (file missing, package missing), the app falls back to fog_core's own
# detector driving the cue, so the board still works on its own.

import os
import tempfile

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import *
from fastapi.responses import FileResponse, JSONResponse

from fog_core import FogCore

logger = Logger("FogMonitor")


def writable_dir(preferred):
    """preferred if it can be written to, otherwise a temp folder (lost on reboot)."""
    try:
        os.makedirs(preferred, exist_ok=True)
        with open(os.path.join(preferred, ".write_test"), "w"):
            pass
        os.remove(os.path.join(preferred, ".write_test"))
        return preferred
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), "fog_data")
        os.makedirs(fallback, exist_ok=True)
        logger.warning(f"{preferred} is not writable; using {fallback} (not kept across reboots)")
        return fallback


DATA_DIR = writable_dir(os.environ.get("FOG_DATA_DIR", "/app/data"))
os.environ.setdefault("FOG_DB", os.path.join(DATA_DIR, "device.sqlite3"))

core = FogCore(data_dir=DATA_DIR)
ui = WebUI()


def set_buzzer(on, tempo_bpm=100):
    Bridge.notify("set_cue", bool(on), int(tempo_bpm))   # notify, not call: never wait on the STM32


api_source = None
try:
    import device_server

    api_source = device_server.start_on_board(cue_hook=set_buzzer, port=8000)
    logger.info("Device API for the phone app is on port 8000")
except Exception as error:   # noqa: BLE001 - any failure here must not stop the board from cueing
    logger.warning(f"Device API not started ({error!r}); the diagnostics detector will drive the cue")


def imu_sample(t_us, ax_mg, ay_mg, az_mg, gx_dps, gy_dps, gz_dps):
    cue_change = core.add_sample(t_us, ax_mg, ay_mg, az_mg, gx_dps, gy_dps, gz_dps)
    if api_source is not None:
        api_source.push(t_us, ax_mg, ay_mg, az_mg)
    elif cue_change is not None:
        set_buzzer(cue_change)


def imu_info(chip_id):
    core.set_chip_id(chip_id)
    logger.info(f"IMU WHO_AM_I = 0x{int(chip_id):02x}")


def api_state(since_sample: int = 0, since_frame: int = 0):
    state = core.state(since_sample, since_frame)
    state["status"]["cue_owner"] = "device_api" if api_source is not None else "page"
    return state


def api_record_start(name: str = ""):
    return core.start_recording(name)


def api_record_stop():
    return core.stop_recording()


def api_label(label: str = ""):
    return core.set_label(label)


def api_response(response: str = ""):
    return core.set_response(response)


def api_recordings():
    return core.list_recordings()


def api_recording(name: str):
    path = core.recording_path(name)
    if path is None:
        return JSONResponse({"error": "no such recording"}, status_code=404)
    return FileResponse(path, media_type="text/csv", filename=path.name)


Bridge.provide("imu_sample", imu_sample)
Bridge.provide("imu_info", imu_info)

ui.expose_api("GET", "/api/state", api_state)
ui.expose_api("POST", "/api/record/start", api_record_start)
ui.expose_api("POST", "/api/record/stop", api_record_stop)
ui.expose_api("POST", "/api/label", api_label)
ui.expose_api("POST", "/api/response", api_response)
ui.expose_api("GET", "/api/recordings", api_recordings)
ui.expose_api("GET", "/api/recording", api_recording)

App.run()
