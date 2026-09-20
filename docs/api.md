# Device API: settings and events

The contract between the device's Linux side (`device/`) and the companion app (`app/`).
Status: implemented by `analysis/src/device_server.py` and consumed by `app/`. Change it here first, then in code.

## Principles

1. **The device is the source of truth and works with no phone.** Settings live on the device and
   survive a reboot. The app is a remote control and a viewer; if it is closed, out of range or
   uninstalled, detection and cueing carry on with the last saved settings. Detection runs on the
   device for this reason (`docs/adr/0001-detection-on-the-device.md`); for the prototype it runs as
   Python on the Linux side rather than C on the STM32
   (`docs/adr/0002-linux-side-python-detector-for-the-prototype.md`).
2. **The app never sends raw detector thresholds.** It picks a named sensitivity preset. The numbers
   behind each preset were measured on patient data (below) and live in the device code.
3. **The device validates everything.** Out-of-range or unknown fields are rejected with `400`; a
   bad request must never leave the detector in an undefined state.
4. **Same schema everywhere.** Events look identical whether the app reads them from the device or,
   later, from a hosted database, so adding cloud sync does not change the app.

Transport: HTTP + JSON on the local network, base URL `http://<device>:8000/api/v1`, plus one
WebSocket at `ws://<device>:8000/api/v1/live` for anything the app must learn about immediately.
REST is for settings, history and actions; the socket is for live state. The app finds the device by
its address, typed once and remembered: there is no discovery protocol. No auth for the demo (say so
in the writeup; real use needs pairing and encryption, this is health data).

## Settings

`GET /settings` returns the full object. `PATCH /settings` takes any subset and returns the full
updated object.

| field | type | default | allowed | what it does |
|---|---|---|---|---|
| `detection_enabled` | bool | `true` | | master switch for automatic detection |
| `sensitivity` | string | `"balanced"` | `"catch_more"`, `"balanced"`, `"fewer_alerts"` | preset, see table below |
| `walking_gate` | bool | `true` | | only start a cue if the wearer was walking in the last 5 s. Off: can catch freezes when starting to walk, but will also beep while standing or sitting |
| `cue_sound` | bool | `true` | | play an audible metronome at all |
| `cue_output` | string | `"phone"` | `"buzzer"`, `"phone"` | where the audible metronome plays. The prototype has no buzzer fitted, so the phone is the default and the fallback below only blinks the board's LED. Only one at a time: two metronomes on two clocks drift apart, and an unsteady beat is worse than none |
| `cue_vibration` | bool | `false` | | a pulse on the same beat: the phone vibrates when `cue_output` is `"phone"`, otherwise the device's vibration motor (not fitted on the prototype) |
| `tempo_bpm` | int | `100` | 60 to 140 | metronome rate. Should be set to the wearer's comfortable stepping rate, ideally with their physio. Fast rates can make gait worse |
| `volume` | int | `70` | 0 to 100 | buzzer loudness |
| `cue_min_seconds` | int | `5` | 3 to 15 | a cue plays at least this long, and keeps going while the freeze continues |
| `log_events` | bool | `true` | | store freeze events |

At least one of `cue_sound` / `cue_vibration` must stay on while `detection_enabled` is true; the
device rejects a change that would silence both.

`cue_output: "phone"` makes the wearer's phone the cue, so the device needs no sounder of its own. The
app plays the beat on receiving `cue_started` (below) and stops on `cue_stopped`. **If no app is
connected when a cue starts, or the last app disconnects while one is playing, the device plays it on
the buzzer**, because a setting must never leave the wearer with no cue; `cue.output` says which one is
playing. The app closes its connection when it goes to the background (a phone cannot keep a beat with
its timers suspended), which hands the cue to the buzzer in the same way.

**The limit of a phone cue.** A phone app only runs timers and receives messages while it is open on
screen. Locked, or in the background, it can neither hear `cue_started` nor keep a beat, so no cue plays. The
app keeps the screen awake while it is open and closes its connection when it leaves the foreground, which the
device sees (`status.apps_connected` drops to 0) and answers by using its own output. With no buzzer fitted
that output is only an LED, so on this prototype **an app that is not open means no audible cue**. Fitting the
piezo (the sketch already drives `BUZZER_PIN`) turns that fallback back into a real one.

### Sensitivity presets

All presets use the 4 s recency-weighted window, the stop rule (a window whose power is still collapsing is
the wearer stopping, not freezing) and the walking gate + 5 s hold. Results are episodes caught and
false cues per hour on the two patient datasets (Mendeley was never used for tuning).

| preset | freeze index > | band power > | consecutive windows | Daphnet | Mendeley |
|---|---|---|---|---|---|
| `catch_more` | 1.056 | 178 mg^2 | 1 | 95%, 58/h | 92%, 63/h |
| `balanced` | 1.056 | 178 mg^2 | 2 | 93%, 47/h | 90%, 48/h |
| `fewer_alerts` | 1.656 | 13,335 mg^2 | 2 | 82%, 23/h | 73%, 23/h |

`catch_more` is also the fast-response setting: on healthy volunteers simulating a freeze straight after
walking, median time to cue was 1.2 s against 1.8 s for `balanced`. On our own two volunteers (12 simulated
freezes) both presets caught 12/12 with no false cues, at a median 1.6 s and 2.1 s.

These rates are for Parkinson's patients in provocation protocols. They are not predictions for
the prototype or for healthy volunteers, and the amplitude thresholds may need shifting once there
are recordings from the real sensor.

## Actions

| request | body | effect |
|---|---|---|
| `POST /cue/start` | `{"seconds": 10}` (3 to 60) | wearer-triggered metronome, independent of detection. Logged as an event with `trigger: "manual"` |
| `POST /cue/stop` | `{"feedback": "false_alarm"}` (optional) | stop the cue that is playing and optionally record the wearer's verdict on it. Answers `{"stopped": true, "event_id": n}`, or `{"stopped": false, "event_id": null}` when nothing was playing, so a late STOP can never mark an older event. After the wearer stops an automatic cue, no new one starts until the detector has let go of that freeze |
| `POST /pause` | `{"minutes": 15}` (1 to 240) | suspend automatic detection (sitting in a car, at dinner). Resumes by itself |
| `POST /resume` | | end a pause early |
| `POST /cue/test` | | 2 s of the current cue settings, for setup |
| `POST /time` | `{"now": "2026-09-19T15:04:05Z"}` | set the device clock. The app sends this on every connect |

## Status

`GET /status`

```json
{
  "device_time": "2026-09-19T15:04:05Z",
  "sensor_ok": true,
  "sample_rate_hz": 64.0,
  "state": "walking",
  "cue_active": false,
  "cue": null,
  "paused_until": null,
  "events_today": 7,
  "uptime_s": 5321,
  "firmware": "0.1.0",
  "source": "bridge",
  "replay": false
}
```

`cue` is the cue playing right now, `{"event_id", "output", "tempo_bpm", "trigger"}` (the same fields as the
`cue_started` message), or `null`. It lets an app that connects in the middle of a cue show STOP and join the
beat. `replay` is true when the server replays a recording instead of reading the sensor; `source` names it.

`state` is one of `"still"`, `"walking"`, `"freeze_detected"`. `sample_rate_hz` is measured, not
nominal: if it drifts from 64 the detector's frequency bands are wrong, so the app should warn.

## Live channel

`ws://<device>:8000/api/v1/live`. One JSON message per line, each with a `type` and a `device_time`.
The app subscribes on connect and falls back to polling `GET /status` every few seconds if the
socket drops; nothing here is unique to the socket, so a missed message costs liveness, never data.

| `type` | payload | when |
|---|---|---|
| `status` | the `GET /status` body | on connect, then whenever `state` or `cue_active` changes, and at least every 5 s as a heartbeat |
| `cue_started` | `{"event_id": 412, "output": "buzzer", "tempo_bpm": 100, "trigger": "auto"}` | the instant a cue starts. `output` is what actually played, after the fallback rule above |
| `cue_stopped` | `{"event_id": 412, "reason": "finished"}` | `reason`: `"finished"`, `"stopped_by_user"`, `"paused"` |
| `event_created` | the full event object from `GET /events` | when an event is closed and written to the log, which is after `cue_stopped` |

The event is not final when the cue starts: `duration_s` and `walking_resumed_s` are only known
afterwards. So `cue_started` carries an `event_id` the app can hold, and `event_created` delivers the
finished record under that same id.

## Time

The device has no guaranteed battery-backed clock, so after a power cycle its time may be nonsense
and every chart drawn from its events would be wrong. The device still timestamps its own events —
the app is often closed or out of range when they happen, so arrival time is not event time — and
the app corrects the clock with `POST /time` on every connect. `GET /status` returns `device_time`
so the app can show a warning when the two disagree by more than a few seconds.

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
  use, so make it one tap in the app. The STOP button on the live screen is that tap: stopping a cue
  by hand both calls `POST /cue/stop` and marks the event `false_alarm`, with an undo in the app for
  the wearer who stopped a cue during a real freeze. Events can also be marked later from the
  history list. Stopping a cue never suspends detection — that is `POST /pause`, deliberately
  separate, so the device is never silently disarmed.

`GET /events/summary?days=14` returns per-day counts (`auto`, `manual`, `false_alarm`) and mean
duration, for the trend chart shown to a doctor or physio.

## Developing without hardware

Build the app against a mock of this API: a server in `analysis/` that feeds a Daphnet recording
through `src/streaming_detector.py` and serves everything above — same REST routes, same WebSocket,
same schemas. Every screen can then be built, and the whole thing demoed, before the board works.

It has three modes:

- **real-time replay**: a subject's recording at 1x, for an honest end-to-end run
- **compressed replay**: the same recording sped up, to fill the history screen with a plausible
  fortnight in a few seconds
- **manual trigger**: `POST /debug/freeze`, which starts a cue immediately

The manual trigger exists because waiting for a genuine freeze in a 90-second demo is not an option.
**It must never exist on the real device**, or a demo will show a cue the detector never produced
and nobody will notice. It is the one route in this document that is mock-only.

## Open questions

- How the Linux side hands new settings to the STM32. The Bridge is MessagePack-RPC over a local
  socket, callable from plain Python, so an RPC call is the likely answer; how fast a setting takes
  effect is still unmeasured. With the detector on the Linux side (ADR-0002), most settings never
  reach the STM32 at all — only the cue ones do.
- Whether `volume` is meaningful for a piezo on a digital pin; it may need PWM or become on/off.
- Cue latency with the detector on the Linux side (ADR-0002): the STM32 -> Linux hop plus Python
  scheduling jitter is unmeasured, and only matters if it is large against the 1.8 s detection
  latency.
- Getting the board onto the demo network. The UNO Q has dual-band Wi-Fi and runs Debian, so serving
  this API from Python is a settled yes, but **Wi-Fi is provisioned over USB from App Lab**: the
  hotspot has to be configured into the board before the demo, not at it, and again if the hotspot's
  name changes. The board's address on that network is unknown until it joins, which is why the app
  asks the wearer to type it rather than discovering it.
- Whether the UNO Q can instead host its own access point, which would remove the phone-hotspot
  dependency entirely. Unverified, and worth ten minutes of someone's time.
