# Linux side of the Freezing of Gait Monitor app on the Arduino UNO Q.
#
# Receives IMU samples from the sketch over the Bridge, runs the detector (fog_core.py), tells
# the sketch when to play the cue, and serves the web page in ../assets on port 7000 so any
# phone or laptop on the same Wi-Fi can open http://<board-address>:7000
#
# All the logic lives in fog_core.py, which can also be run on a laptop through ../dev_server.py.

import os

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import *
from fastapi.responses import FileResponse, JSONResponse

from fog_core import FogCore

logger = Logger("FogMonitor")
core = FogCore(data_dir=os.environ.get("FOG_DATA_DIR", "/app/data"))
ui = WebUI()


def imu_sample(t_us, ax_mg, ay_mg, az_mg, gx_dps, gy_dps, gz_dps):
    cue_change = core.add_sample(t_us, ax_mg, ay_mg, az_mg, gx_dps, gy_dps, gz_dps)
    if cue_change is not None:
        Bridge.notify("set_cue", cue_change)   # notify, not call: never block the sample stream on a reply


def imu_info(chip_id):
    core.set_chip_id(chip_id)
    logger.info(f"IMU WHO_AM_I = 0x{int(chip_id):02x}")


def api_state(since_sample: int = 0, since_frame: int = 0):
    return core.state(since_sample, since_frame)


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
