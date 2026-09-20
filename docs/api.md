# Device API: settings and events

The contract between the device's Linux side (`device/`) and the companion app (`app/`).
Status: **draft, nothing implemented yet.** Change it here first, then in code.

## Principles

1. **The device is the source of truth and works with no phone.** Settings live on the device and
   survive a reboot. The app is a remote control and a viewer; if it is closed, out of range or
   uninstalled, detection and cueing carry on with the last saved settings.
2. **The app never sends raw detector thresholds.** It picks a named sensitivity preset. The numbers
   behind each preset were measured on patient data (below) and live in the device code.
3. **The device validates everything.** Out-of-range or unknown fields are rejected with `400`; a
   bad request must never leave the detector in an undefined state.
4. **Same schema everywhere.** Events look identical whether the app reads them from the device or,
   later, from a hosted database, so adding cloud sync does not change the app.

Transport: HTTP + JSON on the local network, base URL `http://<device>:8000/api/v1`. No auth for the
demo (say so in the writeup; real use needs pairing and encryption, this is health data).

## Settings

`GET /settings` returns the full object. `PATCH /settings` takes any subset and returns the full
updated object.

| field | type | default | allowed | what it does |
|---|---|---|---|---|
| `detection_enabled` | bool | `true` | | master switch for automatic detection |
| `sensitivity` | string | `"balanced"` | `"catch_more"`, `"balanced"`, `"fewer_alerts"` | preset, see table below |
| `walking_gate` | bool | `true` | | only start a cue if the wearer was walking in the last 5 s. Off: can catch freezes when starting to walk, but will also beep while standing or sitting |
| `cue_sound` | bool | `true` | | metronome on the buzzer |
| `cue_vibration` | bool | `false` | | vibration motor pulses on the same beat |
| `tempo_bpm` | int | `100` | 60 to 140 | metronome rate. Should be set to the wearer's comfortable stepping rate, ideally with their physio. Fast rates can make gait worse |
| `volume` | int | `70` | 0 to 100 | buzzer loudness |
| `cue_min_seconds` | int | `5` | 3 to 15 | a cue plays at least this long, and keeps going while the freeze continues |
| `log_events` | bool | `true` | | store freeze events |

At least one of `cue_sound` / `cue_vibration` must stay on while `detection_enabled` is true; the
device rejects a change that would silence both.

### Sensitivity presets

All presets use the 4 s recency-weighted window and the walking gate + 5 s hold. Results are episodes caught and
false cues per hour on the two patient datasets (Mendeley was never used for tuning).

| preset | freeze index > | band power > | consecutive windows | Daphnet | Mendeley |
|---|---|---|---|---|---|
| `catch_more` | 1.056 | 178 mg^2 | 1 | 96%, 61/h | 92%, 61/h |
| `balanced` | 1.056 | 178 mg^2 | 2 | 95%, 51/h | 91%, 45/h |
| `fewer_alerts` | 1.656 | 13,335 mg^2 | 2 | 84%, 26/h | 74%, 22/h |

`catch_more` is also the fast-response setting: on healthy volunteers simulating a freeze straight after
walking, median time to cue was 1.2 s against 1.8 s for `balanced` (the web app calls these Fast and Balanced).

These rates are for Parkinson's patients in provocation protocols. They are not predictions for
the prototype or for healthy volunteers, and the amplitude thresholds may need shifting once there
are recordings from the real sensor.

## Actions

| request | body | effect |
|---|---|---|
| `POST /cue/start` | `{"seconds": 10}` (3 to 60) | wearer-triggered metronome, independent of detection. Logged as an event with `trigger: "manual"` |
| `POST /cue/stop` | | stop whatever cue is playing |
| `POST /pause` | `{"minutes": 15}` (1 to 240) | suspend automatic detection (sitting in a car, at dinner). Resumes by itself |
| `POST /resume` | | end a pause early |
| `POST /cue/test` | | 2 s of the current cue settings, for setup |

## Status

`GET /status`

```json
{
  "device_time": "2026-09-19T15:04:05Z",
  "sensor_ok": true,
  "sample_rate_hz": 64.0,
  "state": "walking",
  "cue_active": false,
  "paused_until": null,
  "events_today": 7,
  "uptime_s": 5321,
  "firmware": "0.1.0"
}
```

`state` is one of `"still"`, `"walking"`, `"freeze_detected"`. `sample_rate_hz` is measured, not
nominal: if it drifts from 64 the detector's frequency bands are wrong, so the app should warn.

## Events

`GET /events?since=<ISO time>&limit=100` returns newest first.

```json
{
  "id": 412,
  "start": "2026-09-19T14:58:12Z",
  "duration_s": 7.5,
  "trigger": "auto",
  "peak_freeze_index": 3.4,
  "cue": {"sound": true, "vibration": false, "tempo_bpm": 100},
  "walking_resumed_s": 4.0,
  "sensitivity": "balanced",
  "feedback": null
}
```

- `trigger`: `"auto"` or `"manual"`.
- `peak_freeze_index`: highest value during the event; the nearest thing to a confidence score that
  the detector has. Show it as weak / strong, not as a probability.
- `walking_resumed_s`: seconds from cue start until locomotion-band power was back above the walking
  level, or `null` if it did not happen within 15 s.
- `feedback`: `null`, `"real"` or `"false_alarm"`, set with `PATCH /events/{id}` body
  `{"feedback": "false_alarm"}`. This is the only ground truth the device will ever get from real
  use, so make it one tap in the app.

`GET /events/summary?days=14` returns per-day counts (`auto`, `manual`, `false_alarm`) and mean
duration, for the trend chart shown to a doctor or physio.

## Developing without hardware

Build the app against a mock of this API. The plan is a small server in `analysis/` that replays
detector output from a Daphnet recording as live status and events, so every screen can be built
and demoed before the board works.

## Open questions

- How the Linux side hands new settings to the STM32 (Bridge/RPC call vs. a settings message on the
  existing link) and how fast they take effect. Not verified against the UNO Q documentation.
- Whether `volume` is meaningful for a piezo on a digital pin; it may need PWM or become on/off.
- Time sync: the device has no battery-backed clock guarantee. The app may need to set device time
  on connect.
