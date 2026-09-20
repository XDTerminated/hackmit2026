# device

Everything that runs on the Arduino UNO Q.

## What is here

| folder | status | what it is |
|---|---|---|
| `bringup/GyroTestCodeWorking.ino` | works on the board | first contact with the IMU: prints accel, gyro and compass readings about 3 times a second as text. Keep as a wiring test |
| `fog_app/` | **runs on the board** (64.0 Hz, no lost samples), worn by two volunteers | App Lab app: streams the IMU over the Bridge, runs the detector and the device API (port 8000, with the demo screen at `/demo`) on the Linux side, serves the diagnostics page on port 7000, records labelled sessions. See its README |
| `detector/` | not started | hardware-free C port of the detector, tested on a laptop against `../test_vectors/` |

Known from the bring-up sketch: the sensor is on **Wire2** (A4 = SDA, A5 = SCL), address **0x68**; plain
`Wire` is the other SDA/SCL pair next to AREF. On the UNO Q every `Serial.print()` call reaches the Linux
side as a separate message, so build output into one string and print it once. The chip can reset itself
to sleep mode after a brief power dip (loose wire), losing its range settings; both sketches detect that
and re-initialise.

## Next steps on the board

1. Wear it, record a few minutes from the diagnostics page on port 7000 (stand still 30 s, walk 60 s,
   stand, walk), download the CSV and run `uv run src/check_recording.py <file>` in `analysis/`. It checks the rate, lost samples,
   gravity scale, clipping, and whether still and walking separate in band power the way they do in the
   patient data.
2. Once that passes, record labelled sessions (walking / standing / simulated freezing, each state held
   for 10 s or more) and re-check the amplitude thresholds.
3. Port the detector: keep `detector/` free of Arduino headers so it can be proven against the test
   vectors on a laptop, then call it from the sketch once per sample.

## Settings the data says matter

- Accelerometer range **+-8 g**. The MPU-9250 defaults to +-2 g; patients' heel strikes reach 4-5 g
  in both datasets, so +-2 g would clip constantly and corrupt the spectrum.
- Sample from a hardware timer, not `delay()`. The detector assumes exactly 64 Hz.
- IMU digital low-pass filter around 20-40 Hz to avoid aliasing.
- Convert to milli-g before the detector: the 178 and 10,000 mg^2 thresholds assume it.
- First milestone is streaming raw samples to the laptop as CSV (`t_ms, acc_x, acc_y, acc_z,
  gyr_x, gyr_y, gyr_z`), so the analysis scripts can be run on your own recordings.

## Bridge and App Lab, from Arduino's published examples

App layout: `app.yaml` (lists bricks), `sketch/sketch.ino` + `sketch.yaml` (platform `arduino:zephyr`),
`python/main.py`, `assets/` (web page, needs `index.html`). Sketch side: `#include <Arduino_RouterBridge.h>`,
`Bridge.begin()`, `Bridge.notify("name", args...)` to push data, `Bridge.provide("name", fn)` to be called.
Python side: `from arduino.app_utils import *`, `Bridge.provide`, `Bridge.notify`, `Bridge.call`, `App.run()`.
Web: `from arduino.app_bricks.web_ui import WebUI`, serves `assets/` on port 7000, `ui.expose_api(method, path, fn)`.
Sources: github.com/arduino/app-bricks-examples, github.com/arduino/app-bricks-py, github.com/arduino-libraries/Arduino_RouterBridge.

## Not verified yet

Power draw (Arduino specifies 5 V / 3 A; whether a phone's USB-C port can power the board is untried), the
cue output on a real buzzer, and the polarity of `LED_BUILTIN` (see `fog_app/README.md`).
