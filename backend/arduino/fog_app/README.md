# fog_app: live monitor over Wi-Fi

An Arduino App Lab app for the UNO Q. The STM32 reads the IMU at 64 Hz and the Linux side serves two things
over Wi-Fi:

- **port 8000, the device API** from `docs/api.md` (`backend/api/device_server.py`, copied onto the board by
  `deploy.sh`): detector, sensitivity presets and settings, SQLite event log, REST + WebSocket. The phone app
  in `frontend/` talks to this, and it owns the cue: it tells the STM32 when to play the buzzer and at what tempo.
- **port 7000, a diagnostics page** (`fog_core.py` + `assets/`): live charts, the sample-rate check and
  labelled recording.

If the device API cannot start on the board, the diagnostics detector drives the cue instead, so the board
always works on its own.

```
sketch/sketch.ino   STM32: IMU at 64 Hz -> Bridge.notify("imu_sample", ...); plays the cue on set_cue()
python/main.py      Linux: Bridge + WebUI glue (needs the board)
python/fog_core.py  Linux: live state, events and labelled recording for the diagnostics page, around the
                    shared detector in backend/api/streaming_detector.py (no board needed)
assets/             the web page: index.html, app.js, style.css (no external libraries)
dev_server.py       runs the same page and API on a laptop, replaying recorded data
app.yaml            App Lab manifest; uses the arduino:web_ui brick
```

## What the page shows

Current state (still / moving / walking / freeze detected), the freeze index and movement power
with their thresholds, the measured sample rate and lost samples (the detector's frequency bands
are only right at 64 Hz), a 10 s movement trace, 2 minutes of freeze index with cue periods shaded,
and the list of detected events.

It also records labelled sessions: press **Start recording**, then an observer taps Walking /
Standing / Freezing (or the W / S / F keys, N for none) as the wearer moves. Recordings are CSV
files in the same format `backend/analysis/check_recording.py` reads, with the label as the last
column, and can be downloaded from the page.

## What has and has not been tested

Tested on a laptop with `dev_server.py`: every API route, recording and download, and a downloaded
recording passes through `check_recording.py`. The page was rendered and checked in a browser. The
detector is the project's reference implementation, checked against the firmware test vectors with
`uv run analysis/verify_detector.py --check-vectors` in `backend/`.

Verified on the board (2026-09-19): the sketch compiles and flashes, samples arrive over the Bridge at
64.0 Hz with none lost, gravity reads 1047 mg (the patient datasets read 1030-1080), a board lying still
reads 1 mg² of band power, the diagnostics page is served on port 7000 and the device API on port 8000. The sensor reports WHO_AM_I 0x68,
so the GY-9250 breakout carries an MPU6050/9150-class chip.

Worn on a leg by two volunteers (2026-09-20): walking power ~10^5 mg², standing ~9 mg², 12/12 simulated freezes
cued, recording to `/app/data` works (see CLAUDE.md, "Own recordings"). **Not yet tested:** a real buzzer on
`BUZZER_PIN` (none is fitted; the phone is the cue), and whether `LED_BUILTIN` is lit by HIGH or by LOW on this
board (Arduino's UNO Q blink example says LOW; the sketch writes HIGH on the beat).

## Try it on a laptop first

```
python backend/arduino/fog_app/dev_server.py            # replays real patient data from test_vectors/
python backend/arduino/fog_app/dev_server.py --replay path/to/recording.csv --speed 4
```

Then open http://localhost:7000

## Run it on the board

One-time setup: the board must have been through App Lab's first-run setup (firmware update, Wi-Fi,
and a password for the `arduino` user). Wiring as in `../bringup/`: IMU on A4 (SDA) / A5 (SCL) and
3.3 V; buzzer on pin 8 (`BUZZER_PIN` in `sketch.ino`, `-1` for LED only; the pin goes HIGH on each
beat, which suits an active buzzer, while a passive piezo needs a square wave instead).

Apps live in `~/ArduinoApps/<name>/` on the board and are run with `arduino-app-cli`. From the repo
root on your laptop, with the board's address in place of `BOARD` (find it in App Lab, or on the
board with `ip addr show` under `wlan0`):

```
bash backend/arduino/fog_app/deploy.sh          # over USB: copy, restart, forward ports 7000 and 8000, show the log
bash backend/arduino/fog_app/deploy.sh logs     # just the log
```

The script also copies `device_server.py`, `streaming_detector.py`, `cadence.py` and `demo_page.html` from
`backend/api/` into the app's `python/` folder; without them the app cannot start. Without USB, the same
files can be copied by hand into `~/ArduinoApps/fog_app/` with `scp`, then
`ssh arduino@BOARD "arduino-app-cli app stop user:fog_app; arduino-app-cli app start user:fog_app"`.

The first start is slow: it compiles the sketch, flashes the STM32 and prepares the Python
environment. Stop whatever other app is running first (`arduino-app-cli app stop <path>`). The app
should also show up in App Lab under your apps, where you can run it and read its console instead.

Then, from any device on the same Wi-Fi, open `http://BOARD:7000`.

What to look at first:

| you see | meaning |
|---|---|
| "no sensor data yet" | the page works but no samples arrive: read the logs. A sketch compile error, the IMU not answering (check the bring-up sketch still works), or the Bridge not delivering `imu_sample` |
| **Sample rate** not 64.0 Hz, or **Samples lost** climbing | the Bridge cannot keep up with one message per sample; the sketch should then send several samples per `notify` |
| state stuck on "Still" while walking | check **Movement power**: walking should be above 10,000 mg². If it is far lower, the accelerometer scale or mounting differs from the datasets and the amplitude thresholds need shifting |
| recording fails to start | `/app/data` is not writable in the app's container: set `FOG_DATA_DIR` to a writable path |
| Python import error for `numpy` in the logs | add `python/requirements.txt` containing `numpy` |

After editing files, copy them again and restart: `app stop`, then `app start`.

### Wi-Fi

The board rejoins a network it knows, and the phone and laptop must be on that same network. Two things
have gone wrong here before:

- **It joined a different network from the phone.** With equal priorities NetworkManager picks the network
  it used last, which at a venue is often a guest network. The priorities are now set on the board (over USB,
  `adb shell`): `nmcli connection modify "iPhone 16 Pro" connection.autoconnect-priority 100`, the other
  hotspot 90, HackMIT 50, and `nmcli connection modify "@Hyatt_WiFi" connection.autoconnect no`. To move it by
  hand: `nmcli connection up "<network name>"`. To see where it is: `nmcli -t -f ACTIVE,SSID dev wifi`.
- **Guest and hotel networks do not work**: they need a browser login the board cannot do, and they block
  devices from reaching each other. Use a phone hotspot. Measured on one: API median 29 ms, a cue message
  reaches a client in about 50 ms.

- **No phone data to spare: use the laptop as the hotspot.** Windows Settings > Network & internet > Mobile
  hotspot shares the laptop's connection (hotel Wi-Fi included) on its own network; the board and the phone
  join that, and the phone keeps internet through the laptop. The board knows it as `laptop-hotspot`
  (priority 110, above the phone hotspots) and gets an address in 192.168.137.x. Tested on the hotel Wi-Fi,
  where laptop and board could not reach each other directly (client isolation, confirmed): API median 34 ms
  through the laptop hotspot, no lost samples. Windows switches the hotspot off when nothing is connected for
  a while (turn off "Power saving" on that settings page), and the laptop has to stay within Wi-Fi range.

The address changes with the network; `arduino.local` does not. `deploy.sh` prints both.

### Running from a power bank with no laptop

The app is set as the board's startup app (`arduino-app-cli properties set default user:fog_app`, or the
"Run at startup" switch in App Lab), so it starts by itself about a minute after power is applied. The board
rejoins a Wi-Fi network it already knows; open `http://<board-ip>:7000` from a phone on that network. To undo:
set another app as default in App Lab. Detection and the cue do not need Wi-Fi or an open page.

## Where the detector runs

Here it runs in Python on the board's Linux side. That is still on the device and needs no
network, and it made a working end-to-end loop possible quickly. The plan of record is to move
it onto the STM32 as C (`../detector/`), at which point `main.py` only logs and serves, and the
cue keeps working even if the Linux side is busy or restarting.
