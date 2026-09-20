# Freezing-of-gait detector: project notes

Shin-worn prototype for HackMIT 2026: an IMU detects freezing of gait (FoG) in Parkinson's disease,
the wearer's phone plays a metronome cue at their own walking pace, events are logged for a companion app. Class/demo project,
**not a medical device**, never tested on patients; demos use healthy volunteers simulating freezes.

Hardware: Arduino UNO Q (Qualcomm Linux side + STM32, 3.3 V logic, Bridge/RPC via App Lab),
GY-9250 breakout over I2C (accel + gyro only; the chip is MPU6050-class, see Device notes). No buzzer or vibration
motor is fitted: the phone is the cue, and the sketch still drives a buzzer pin as the fallback. Power over USB-C
(laptop or charger; no power bank so far, and whether a phone can power the board is untested).

## Repo layout

Polyglot monorepo; each part has its own README and tooling, and the parts share no code.

- `analysis/` Python (uv). Working. Scripts in `analysis/src/`, run as `uv run src/<name>.py` from `analysis/`.
  Paths are resolved from the repo root, so scripts work from any directory.
- `device/` UNO Q code: `device/fog_app/` is the App Lab app that runs on the board, `device/bringup/` the wiring
  test. It ships three files from `analysis/src/` (see Status). `device/detector/` (hardware-free C) is deferred.
- `app/` companion phone app, Expo (React Native, TypeScript).
- `test_vectors/` contract between `analysis/` and `device/`. Its README is the firmware spec.
- `docs/` dataset docs and licences; `docs/api.md` is the device-to-app contract: user settings,
  sensitivity presets with measured trade-offs, actions, status, events. Change it there first, then in code.
- `data/<dataset>/raw` and `/clean` are gitignored. See README.md for how to fetch them.

## Status (2026-09-20, branch `board-integration`, local only)

**Analysis (works).** Daphnet and Mendeley cleaning, Freeze Index baseline, cue-logic simulation, latency, gyro,
calibration and random-forest experiments, the streaming reference detector and the firmware test vectors.
Shared evaluation code lives in `baseline_fi.py` (`window_features`, `detect`/`debounced`, `grid_counts`,
`loso_cell`, `score_subject`, `summary_row`, `event_metrics`); the experiment scripts only add what is specific
to them. `streaming_detector.py` holds the one detector (`StreamingDetector`) and `SampleClock` (delivered
sample rate and lost samples); `--verify` checks it against the batch code, `--check-vectors` against
`test_vectors/`.

**Device (runs on the board).** `device/fog_app/` is the App Lab app: the sketch samples the IMU at 64 Hz and
pushes each sample over the Bridge; `python/main.py` feeds two consumers. Port 8000 is the device API
(`analysis/src/device_server.py`, Khai's server: presets and settings, SQLite event log, REST + WebSocket); it
owns the cue and plays it at the wearer's own cadence (auto tempo, `cadence.py`). `http://<board>:8000/demo` is
the demo screen (`demo_page.html`, fed by `GET /api/v1/frames`): what the real detector sees and decides, for a
projector; it polls rather than use the WebSocket so it never counts as a connected phone. Port 7000 is the
diagnostics page (`fog_core.py`): live charts, sample-rate check, labelled recording. If the API cannot start, the page's detector drives the cue.
`bash device/fog_app/deploy.sh` deploys over USB (App Lab's adb), ships `device_server.py`,
`streaming_detector.py`, `cadence.py` and `demo_page.html` with the app, and forwards both ports to localhost. The
app is the board's startup app.
Verified on the board: 64.0 Hz, no lost samples with both consumers, gravity 1047 mg, a still board reads
1 mg^2, API reachable over USB and over the HackMIT Wi-Fi, WebSocket cue messages, no debug route.
`device/bringup/` is the original wiring-test sketch. Wi-Fi: the board must share a network with the phone; a phone
hotspot works (API median 29 ms, cue message ~50 ms), guest/hotel networks do not (captive portal, client
isolation, confirmed on the Hyatt network); with no phone data to spare, the laptop's Windows Mobile hotspot works
(`laptop-hotspot`, board at 192.168.137.x, API median 34 ms). Auto-join priorities are set on the board with nmcli
(laptop hotspot, then phone hotspots; hotel Wi-Fi disabled); see `device/fog_app/README.md`.

**App (runs on a phone in Expo Go against the board; the team reports it works, auto tempo not yet tried worn).**
Expo SDK 57, tabs Home, My data and Settings, in `app/`, redesigned 2026-09-20 for older wearers with a tremor
(Nunes et al. 2015: 14 mm targets, taps not drags, nothing timed, little per screen; Dexcom-style single status):
Home shows one status and one button and no numbers, a cue takes the screen over with a beat that pulses with
the click and one large STOP, the STOP verdict card has no countdown, setup lives under Settings > Advanced.
Light/dark is Automatic by time of day (7-19 h light) or pinned; that choice and the last working device address
are stored on the phone (`usePreferences.ts`). Checked by screenshots of a web build against a replayed
recording, both themes; not yet on a phone. `src/useDevice.ts` owns the link: one WebSocket, a full REST sync on every
connect, reconnection, and every action through one error path shown on all tabs. The phone cue is a click
and/or a vibration pulse on a drift-corrected beat. `CONTEXT.md` is the glossary; ADR 0001/0002 record
detection-on-device and Python-not-C for the prototype.

Behaviour worth knowing (all tested against the server): STOP holds (no new automatic cue until the detector
lets go of that freeze); a STOP when nothing plays answers `stopped: false`, so it can never mark an older
event; `status.cue` lets an app that connects mid-cue show STOP; when the last app disconnects or goes to the
background during a phone cue, the buzzer takes over; STOP silences the phone before it talks to the device.
Since the second review (2026-09-20, all covered by `check_device_server.py`, which fails on the old server): a cue
the device took over goes back to the phone when it reconnects, and a vanished phone is noticed within ~6 s
(WebSocket ping 3 s); switching detection off or pausing ends an automatic cue, never a beat the wearer asked for;
a stopped beat's timer cannot end the next beat; STOP on a requested beat keeps the automatic cue's latch; a
sensor that goes quiet for 4 s ends the cue (`sensor_lost`); malformed requests answer 400; durations, the pause
and `walking_resumed_s` use a monotonic clock; `walking_resumed_s` is now watched from the start of the cue
(before, it could never be shorter than the cue); `peak_freeze_index` only counts positive windows. If the API
thread dies or never binds its port, `LiveSource.alive()` turns false and `main.py` hands the cue to the
diagnostics detector. The app has a 12 s silence watchdog, never opens a second socket, and matches
`cue_stopped` to the cue it is playing. The `volume` and `log_events` settings were removed: nothing honoured them.
The presets are defined once, in `streaming_detector.PRESETS`.
On the board the API has no authentication and no CORS headers (which is not protection: bodiless POSTs and the
WebSocket are not subject to CORS); the wildcard CORS rule exists only in laptop replay.

Open decisions from the code review, not yet made: day boundaries are UTC on the server but times are shown
locally (cues after 8 pm Boston time count as tomorrow); "cues today" is all events on Now but excludes false
alarms on History; settings switches wait for the device's answer instead of updating optimistically; the History chart's bars are narrow tap targets with no screen-reader
alternative. From the second review, also open: the History toggle turns a `real` verdict into `null`
after two taps; a dev or store build would need cleartext-HTTP and iOS
local-network permissions in `app.json` (Expo Go does not); the diagnostics page (port 7000) always runs the
balanced preset, so it can disagree with the real cue; `LED_BUILTIN` polarity is unchecked; `fewer_alerts` caught
only 10/12 of our own simulated freezes.

Not done: a worn test of auto tempo and of the demo screen; a stop-and-start session from a third person (the
stop rule is provisional); the C port (`device/detector/`, deferred by ADR 0002).

## The detector (v3: recency-weighted window + stop rule; port this)

Input: acceleration magnitude in **milli-g** at **64 Hz**. Window 256 samples (4 s), step 32 (0.5 s), in time
order, weighted `w[i] = i/255` (oldest 0, newest 1), weighted mean removed, 256-point FFT, bin k = k x 0.25 Hz,
`bin_power = |Y|^2 * 2 / (256 * sum(w^2))` (so a band sum is the weighted variance in that band, mg^2).
v1 had no weighting and no stop rule; v2 added the weighting; v3 (current, 2026-09-20) adds the stop rule.
Every Daphnet/Mendeley number below marked (v1) was measured with v1.

    loco   = sum(bins 2..11)     # 0.5-3 Hz
    freeze = sum(bins 12..32)    # 3-8 Hz
    total    = loco + freeze
    stopping = total < 0.6 * previous frame's total        # never on the first frame
    positive = freeze/loco > 1.056 and total > 178 and not stopping

Cue logic per frame: start a cue after 2 consecutive positive frames if at least 2 of the last 10
frames had `loco > 10000` (walking gate); hold at least 10 frames; keep playing while positive.
**The gate only controls cue start, never continuation** (a long freeze has no recent walking; gating
continuation dropped sensitivity to 0.28).

Reference: `analysis/src/streaming_detector.py`. It matches the batch code on all 35,405 Daphnet
frames with zero cue mismatches, and float32 changes no decisions (v2 re-verified), so single-precision on the
STM32 is safe. The ring buffer must be read in time order now (v1 could skip that).

## Latency and the weighted window (2026-09-19)

On the real board the cue lagged 3-4 s after an abrupt simulated freeze. Cause: the 4 s window is dominated by
the walking that preceded the freeze (patients' gait degrades gradually, which hid this in the datasets).
`latency_experiment.py`, cue logic gate + hold, debounce 2, thresholds unchanged:

| window | healthy sim. freeze latency (median / worst) | Daphnet caught, false cues/h | Mendeley caught, false cues/h |
|---|---|---|---|
| v1: rect 4 s | 2.4 / 4.0 s | 91%, 47 | 88%, 37 |
| rect 2 s | 1.8 / 3.3 s | 95%, 71 | 93%, 60 |
| **v2: linear ramp 4 s** | 1.8 / 3.0 s | 95%, 51 | 91%, 45 |
| v2 with debounce 1 ("fast") | 1.2 / 2.5 s | 96%, 61 | 92%, 61 |

The ramp dominates shortening the window. Steeper weighting or shorter windows go faster still (0.6 s) but false
cues roughly double. Healthy data: 13 freeze bouts from 2 people in an external repo, labels pressed by hand, so
the latencies are rough. The choice was made looking at all data, not nested.

### Onset experiment (2026-09-20, `onset_experiment.py`): no cheap way to go faster

Asked to remove the 2-3 s wait on the worn device. The phone and the server add ~0.1 s (first beat is immediate,
cue message ~50 ms); the rest is detection. Per freeze on own recordings: debounce 0.5 s, frame period 0-0.5 s,
and 0-3 s for the pre-freeze walking to fade from the window (a vigorous tremble flips the index in one frame,
a gentle one after brisk walking takes 2-3 s). Tried, v3 thresholds, own median latency / own false cues /
Daphnet / Mendeley (caught, false cues per hour):

| candidate | own | Daphnet | Mendeley |
|---|---|---|---|
| balanced (debounce 2) | 2.1 s, 0 | 93%, 47 | 90%, 48 |
| catch_more (debounce 1) | 1.6 s, 0 | 95%, 58 | 92%, 63 |
| frames every 0.25 s, confirm 0.5 s | 1.8 s, 0 | 94%, 56 | 92%, 54 |
| frames every 0.25 s, confirm 0.25 s | 1.6 s, 2 | 97%, 66 | 93%, 72 |
| + fast path, weights^3, FI > 1.5 for 0.5 s | 1.5 s, 0 | 94%, 56 | 92%, 48 |
| + fast path, weights^3, FI > 1.056 for 0.25 s | 0.8 s, 4 | 96%, 103 | 95%, 106 |

It is one trade-off curve: ~0.5 s costs ~10 false cues/h on patients whichever way it is bought, and sub-second
doubles them. The best fast path beats `catch_more` by 0.1 s on 12 hand-labelled freezes, which is noise, and
would need a v4 spec (0.25 s frames, second FFT, new vectors). **Not adopted; `catch_more` is the fast setting.**
A spectral detector has to see ~1-1.5 s of trembling. Patients' own latencies are shorter (Daphnet 1.2 s,
Mendeley 1.5 s median) because their gait degrades into a freeze; the abrupt stop is a healthy-actor artefact.

## Auto tempo (2026-09-20, `cadence.py`)

The cue plays at the wearer's own cadence, measured on the device: stride time from the autocorrelation of the
acceleration magnitude over 6 s windows that were steady walking end to end (loco > 10,000 mg^2, freeze index
< 0.7, no cue), every 2 s, median of the last 5 min; cadence = 120 / stride time (one shin sees strides, the
other leg's step is a weak peak at half the lag). `cadence.py --check`: all 49 estimates on own recordings within
2.4 steps/min of the stride time from gyro swing peaks; Khai 100.5, Alex 90.6. Deliberately the usual cadence,
not the seconds before the freeze (festination). Factor 1.0: Willems 2006 (-10%) and Arias & Cudeiro 2010 (+10%)
disagree for freezers. Setting `tempo_auto` (default on), `status.cadence_spm` / `cue_tempo_bpm`; `tempo_bpm` is
the fallback until ~10 s of steady walking. Remembered across restarts. Not checked on patient gait (shuffling
steps may have a much weaker stride peak; below strength 0.4 no estimate is made and the fallback applies).

## Findings (v1 detector; Daphnet, leave-one-subject-out, 2 s Baechlin tolerance)

- Raw detector: sens 0.91 / spec 0.84, 226/237 episodes, but **120 false cues per hour**.
  Published subject-independent baseline (Baechlin 2010): 0.73 / 0.82.
- With the cue logic above: 214/237 episodes, **47 false cues/h**, median latency 1.8 s. Choosing the
  cue logic inside each fold (`--nested 0.9`) gives 213/237 and 41/h, so it was not overfit to the test subjects.
- Window length: 2 s halves latency (0.7 s) but doubles false alarms. Use 4 s.
- 144 of 226 detected freezes had the detector already firing before the annotated onset. Partly
  real pre-freeze gait degradation, partly false alarms; the labels cannot separate them.
- S01 and S08 have freeze-like normal gait and account for much of the false-alarm rate.

Tried and rejected (do not re-propose without new data):
- Per-user calibration by normalising the Freeze Index to the user's own walking: sens 0.91 -> 0.78.
  A patient's baseline FI is signal, not nuisance.
- Random forest on 21 magnitude features: equal to the two-threshold detector at every operating
  point. Per-axis features add ~3 points of sensitivity at spec 0.95 and need Daphnet-aligned mounting.
- A refractory period after cues, and a "strict" walking gate that ignores detector-positive frames.
- Gyro turn veto and gyro-based Freeze Index (see Mendeley results).

Known limits: Daphnet labels lump standing/walking/turning, so false alarms while standing cannot be
measured there; the walking gate cannot catch start-hesitation freezes by design; all numbers are
for Daphnet-like patients, not for the device or for healthy volunteers.

## Datasets

**Daphnet** (`data/daphnet`): 10 patients, ankle accelerometer, 64 Hz, 237 freeze episodes, ~10% of
experiment time. Columns 1-3 of the raw files are the ankle (forward, vertical, lateral) in mg; label
0 = not in experiment, 1 = no freeze, 2 = freeze. Cleaning: drop label 0, interpolate 572 glitch
samples (|x| > 6000 mg; the sensor clips near 5000), segment at gaps. Subjects S04 and S10 have no
freezes and are kept as false-alarm tests.

**Mendeley multimodal** (`data/mendeley`, doi:10.17632/r8gmbtv7w2.3): 12 patients, MPU6050 accel + gyro
on both shanks (the device's location and sensor family), 500 Hz, 334 episodes, ~40% freeze time.
IMU columns are raw counts: 8192 LSB/g (+-4 g) and 16.4 LSB/(deg/s) (+-2000 dps), both inferred from
the data (gravity magnitude; quarter turns integrating to 91 deg). Missing sensors are all-zero
columns; the cleaner takes the left shank if present, else the right. Sensor x axis lies along the shank.
Value to us: independent test of the frozen detector, and the only real-patient shank gyro data.

**Kaggle tlvmc FoG competition**: reviewed, not used. Lower-back sensor, and the public notebooks use
future data and patient metadata, so their scores are not comparable to a causal detector.

### Mendeley results (12 patients, 207 min, 324 episodes after cleaning)

External validation: the detector exactly as frozen on Daphnet, nothing re-tuned
(`simulate_device.py --dataset mendeley --fixed-thresholds 1.056 178`).

| | Daphnet (LOSO) | Mendeley (frozen) |
|---|---|---|
| raw detector sens / spec | 0.91 / 0.84 | 0.94 / 0.76 |
| raw detector episodes, false cues/h | 226/237, 120 | 318/324, 115 |
| with cue logic: episodes, false cues/h | 214/237 (90%), 47 | 286/324 (88%), 37 |
| with cue logic: median latency | 1.8 s | 2.0 s |

The approach generalises: different patients, lab, hardware and continent, same body location,
similar results. Specificity is lower (freezes are 40% of this data and its tasks are all turns).
Re-tuning within Mendeley (LOSO) gives 0.91 / 0.86 with FI threshold ~1.5 and power threshold 18-75,
so the FI threshold is the less settled of the two constants; revisit it with own recordings, not before.
Weak spots: M11 (29/51 episodes) and M05 (no freezes, 176 false cues/h, freeze-like gait).

Gyro (`gyro_experiment.py`), both negative:
- Turn veto (suppress detections while the shank rotates about the vertical): no benefit. Yaw rate
  of true and false positives overlaps (medians 7.4 vs 8.2 deg/s); every veto level lost episodes
  without reducing false cues.
- Gyro-based Freeze Index (band powers summed over 3 axes): 0.88 / 0.88 vs accel magnitude 0.91 / 0.86.
  As good, not better. **Never use gyro magnitude for spectral features**: rotation oscillates around
  zero, so the magnitude rectifies it and doubles the step frequency into the freeze band (0.50 / 0.70).
- Conclusion: the accelerometer-magnitude detector stands; the gyro is not needed for detection.
  An accel+gyro combined model was not tried.

### Healthy volunteers simulating freezes (external repo, not our data)

github.com/harryyuncheng/parkinsons-fog-device (ESP32 + MPU6050, laptop-side CNN+LSTM, servo "poke" cue)
contains ~7 min from 2 healthy people labelled walking / standing / freezing. Licence is unclear (README
says GPL-3.0, last commit removed the LICENSE file): borrow ideas, do not copy code or commit their data.
Our frozen detector on it (resampled to 64 Hz, m/s^2 -> mg), counting only 4 s windows that lie inside one state:
positive on 100% of freezing windows (147), 12% of walking (197), 7% of standing (112). Median total power:
standing 14 mg^2, walking 22,800 mg^2, i.e. the two amplitude thresholds sit where expected on an MPU6050.
Caveats: two people, acted freezes, sensor placement unknown, unpaced sampling (244-301 Hz), bouts of a few seconds.
Worth copying as an idea: their live keyboard annotation (W/S/F) while recording; a 3-way label gives the
"standing" class that Daphnet lacks.

### Own recordings (`data/own/raw/`, protocol in `docs/recording-protocol.md`, scored by `evaluate_own.py`)

First worn session, 2026-09-20 (`khai_2nd`, 4 min, healthy volunteer, 6 simulated freezes of ~10 s, labels
pressed live): 64.00 Hz, no lost samples, gravity 1028 mg, peak 6.3 g (so +-8 g was needed). Band power is
bimodal as predicted: standing 9 mg^2, walking 104,000 mg^2, simulated freeze ~8,300 mg^2. Detector unchanged:
balanced caught 6/6, latency median 1.1 s (0.7-3.8 s), 1 false cue; catch_more 6/6, 0.6 s (0.2-3.3 s), 2 false cues.
- Latency tracks how strong the tremble is relative to the walking before it: a vigorous tremble (330,000 mg^2)
  flips the index in one frame, a gentle one (~6,000 after walking at 80,000) waits ~2.5-4 s for the walking
  to fade from the window.
- Second person (`alex_1st`, same protocol): 6/6 caught, latency median 2.4 s (1.3-3.7 s), 1 false cue. Pooled,
  balanced: 12/12 caught, median 2.1 s, 2 false cues in 8 min.
- Both false cues are the same event: a normal stop. As walking power decays out of the window, the index drifts
  above 1 for a frame or two while some power remains (Khai: at ~1,000 mg^2; Alex: already at 18,000 mg^2).
  `stop_veto_experiment.py`: a higher power threshold does NOT generalise (Alex's stop sits above Khai's
  freezes); a higher index threshold (1.75) removes both but slows everything (Khai 1.1 -> 2.0 s, max 7.3 s) and
  loses patient episodes (Daphnet 95% -> 88%, Mendeley 91% -> 81%). **Candidate fix: stop veto** - ignore a window
  whose band power is below 0.6 x the previous window's (a stop collapses by half or more per frame, a freeze
  levels off): both false cues gone, 12/12 caught, latency unchanged, patients near neutral (Daphnet 225 -> 221 of
  237, Mendeley 295 -> 291 of 324, false cues/h 51 -> 47 and 45 -> 48). The 0.6 was picked while looking at these two
  recordings. No third volunteer was available, so it was checked on the only unseen healthy data we have (the
  external repo, 2 other people): no change at all (13/14 caught, same latency, same false cues), i.e. harmless
  there but no benefit shown. **Adopted 2026-09-20 as `DetectorParams.stop_veto_ratio = 0.6` (0 disables), and
  explicitly provisional**: its benefit is only demonstrated on the two recordings it was tuned on. With it, own
  recordings: balanced 12/12, 0 false cues, median 2.1 s; catch_more 12/12, 0 false cues, 1.6 s. Patients, balanced:
  Daphnet 221/237 (93%) at 47/h, Mendeley 291/324 (90%) at 48/h. First thing to re-check on any new person,
  especially a stop-and-start session with no freezes.

## Conventions

- Evaluate by subject (leave-one-subject-out or GroupKFold), never by window. Report sensitivity,
  specificity, episodes detected, false cues per hour and latency; never accuracy.
- Build windows within a `segment` only. Label a window by its last sample (causal).
- Anything tuned while looking at all subjects must be re-checked nested before it is trusted.
- Python: small scripts with a docstring stating what they do and their usage line; shared helpers
  live in `baseline_fi.py`. Units in names or comments (mg, mg^2, dps, frames vs seconds).
- Do not re-tune on the same recordings that results are reported from, especially own recordings.

## Device notes

As built: accelerometer at +-8 g (the default +-2 g clips heel strikes; our own recordings peak at 6.3 g), gyro
+-2000 dps, 20 Hz low-pass in the IMU, converted to mg on the STM32, sampling paced by `micros()` at 15,625 us
(intervals alternate ~14.9 / 15.9 ms, mean 64.00 Hz, which is what the detector needs). The first milestone is
met: band power on the worn sensor is bimodal (standing ~9 mg^2, walking ~10^5), so the amplitude thresholds
stand.

Known from bring-up: IMU on Wire2 (A4/A5), address 0x68; each `Serial.print()` reaches the Linux side as a
separate message (batch output into one print); the chip can drop back to sleep after a power dip and must
be re-initialised. The GY-9250 breakout reports WHO_AM_I 0x68: an MPU6050/9150-class chip, not an MPU-9250 (same family as Mendeley's sensor).

Bridge/App Lab API is documented in `device/README.md`; `notify`/`provide` in both directions and the `web_ui`
brick are exercised by `fog_app` on the board.
On Windows, a Python HTTP server bound to IPv4 only makes every `localhost` request take 2 s (IPv6 tried first);
`dev_server.py` listens dual-stack for that reason.

Unverified: UNO Q power draw (Arduino specifies 5 V / 3 A), and whether
CMSIS-DSP `arm_rfft_fast_f32` uses the same unnormalised FFT convention as NumPy.

## Next steps

1. Worn test of the current build: auto tempo (does the measured pace appear after ~10 s of walking, does the cue
   use it), the demo screen's three acts (stop, freeze, walk out of it), `catch_more` latency as felt.
2. A stop-and-start session with no freezes from anyone new, scored with `evaluate_own.py`: the stop rule's 0.6 was
   tuned on the two recordings it is reported from.
3. Power: try the board on the phone's USB-C port (needs well under 4.5 W); if that works, USB networking to the
   phone is possible (the kernel has NCM/ECM gadget modules; needs the board's sudo password).
4. Feature candidates, in the order proposed: medication-timing log (freezes against hours since the last dose),
   adaptive cue (escalate when walking has not resumed), gait summary from the cadence tracker.
5. `device/detector/`: the C port, still the plan of record (ADR-0002), no longer on the demo path.
