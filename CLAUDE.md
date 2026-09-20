# Freezing-of-gait detector: project notes

Shin-worn prototype for HackMIT 2026: an IMU detects freezing of gait (FoG) in Parkinson's disease,
a buzzer plays a metronome cue, events are logged for a companion app. Class/demo project,
**not a medical device**, never tested on patients; demos use healthy volunteers simulating freezes.

Hardware: Arduino UNO Q (Qualcomm Linux side + STM32, 3.3 V logic, Bridge/RPC via App Lab),
GY-9250 / MPU-9250 over I2C (accel + gyro only), piezo buzzer, optional vibration motor, USB-C power bank.

## Repo layout

Polyglot monorepo; each part has its own README and tooling, and the parts share no code.

- `analysis/` Python (uv). Working. Scripts in `analysis/src/`, run as `uv run src/<name>.py` from `analysis/`.
  Paths are resolved from the repo root, so scripts work from any directory.
- `device/` UNO Q code. Planned: `device/detector/` (hardware-free C) plus the App Lab project.
- `app/` companion mobile app. Planned; Expo (React Native) recommended, not yet confirmed by the team.
- `test_vectors/` contract between `analysis/` and `device/`. Its README is the firmware spec.
- `docs/` dataset docs and licences; `docs/api.md` (draft) is the device-to-app contract: user settings,
  sensitivity presets with measured trade-offs, actions, status, events. Change it there first, then in code.
- `data/<dataset>/raw` and `/clean` are gitignored. See README.md for how to fetch them.

## Status (2026-09-19, branch `board-integration`)

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
owns the cue and drives the buzzer at the wearer's tempo. Port 7000 is the diagnostics page (`fog_core.py`):
live charts, sample-rate check, labelled recording. If the API cannot start, the page's detector drives the cue.
`bash device/fog_app/deploy.sh` deploys over USB (App Lab's adb), ships `device_server.py` and
`streaming_detector.py` with the app, and forwards both ports to localhost. The app is the board's startup app.
Verified on the board: 64.0 Hz, no lost samples with both consumers, gravity 1047 mg, a still board reads
1 mg^2, API reachable over USB and over the HackMIT Wi-Fi, WebSocket cue messages, no debug route.
`device/bringup/` is the original wiring-test sketch.

**App (type-checks and bundles; not yet exercised on a phone against the board).** Expo SDK 57, screens Now,
History and Settings, in `app/`. `src/useDevice.ts` owns the link: one WebSocket, a full REST sync on every
connect, reconnection, and every action through one error path shown on all tabs. The phone cue is a click
and/or a vibration pulse on a drift-corrected beat. `CONTEXT.md` is the glossary; ADR 0001/0002 record
detection-on-device and Python-not-C for the prototype.

Behaviour worth knowing (all tested against the server): STOP holds (no new automatic cue until the detector
lets go of that freeze); a STOP when nothing plays answers `stopped: false`, so it can never mark an older
event; `status.cue` lets an app that connects mid-cue show STOP; when the last app disconnects or goes to the
background during a phone cue, the buzzer takes over; STOP silences the phone before it talks to the device.
On the board the API has no authentication and no CORS; the wildcard CORS rule exists only in laptop replay.

Open decisions from the code review, not yet made: day boundaries are UTC on the server but times are shown
locally (cues after 8 pm Boston time count as tomorrow); "cues today" is all events on Now but excludes false
alarms on History; the device address is not remembered between launches (needs a storage dependency);
`app.json` forces light mode although a dark palette exists, and white-on-accent text in that dark palette is
about 2.2:1; settings switches wait for the device's answer instead of updating optimistically; sensitivity is
three switches rather than a radio list; the History chart's bars are narrow tap targets with no screen-reader
alternative.

Not done: a worn test; own labelled recordings; the C port (`device/detector/`, deferred by ADR 0002).

## The detector (v2, recency-weighted; port this)

Input: acceleration magnitude in **milli-g** at **64 Hz**. Window 256 samples (4 s), step 32 (0.5 s), in time
order, weighted `w[i] = i/255` (oldest 0, newest 1), weighted mean removed, 256-point FFT, bin k = k x 0.25 Hz,
`bin_power = |Y|^2 * 2 / (256 * sum(w^2))` (so a band sum is the weighted variance in that band, mg^2).
v1 was the same with no weighting; every Daphnet/Mendeley number below marked (v1) was measured with it.

    loco   = sum(bins 2..11)     # 0.5-3 Hz
    freeze = sum(bins 12..32)    # 3-8 Hz
    positive = freeze/loco > 1.056 and loco + freeze > 178

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

## Conventions

- Evaluate by subject (leave-one-subject-out or GroupKFold), never by window. Report sensitivity,
  specificity, episodes detected, false cues per hour and latency; never accuracy.
- Build windows within a `segment` only. Label a window by its last sample (causal).
- Anything tuned while looking at all subjects must be re-checked nested before it is trusted.
- Python: small scripts with a docstring stating what they do and their usage line; shared helpers
  live in `baseline_fi.py`. Units in names or comments (mg, mg^2, dps, frames vs seconds).
- Do not re-tune on the same recordings that results are reported from, especially own recordings.

## Device notes

Set the accelerometer to +-8 g (default +-2 g clips heel strikes, which reach 4-5 g in both datasets).
Sample from a hardware timer. IMU low-pass ~20-40 Hz. Convert to mg first. First milestone: stream
raw CSV to the laptop and confirm total band power is bimodal (tens of mg^2 still, >10^4 walking);
if not, the amplitude thresholds need shifting before any C is written.

Known from bring-up: IMU on Wire2 (A4/A5), address 0x68; each `Serial.print()` reaches the Linux side as a
separate message (batch output into one print); the chip can drop back to sleep after a power dip and must
be re-initialised. The GY-9250 breakout reports WHO_AM_I 0x68: an MPU6050/9150-class chip, not an MPU-9250 (same family as Mendeley's sensor).

Bridge/App Lab API is documented in `device/README.md` (taken from Arduino's example repos, not yet exercised by us).
On Windows, a Python HTTP server bound to IPv4 only makes every `localhost` request take 2 s (IPv6 tried first);
`dev_server.py` listens dual-stack for that reason.

Unverified: UNO Q power needs, anything in `device/` on real hardware, and whether
CMSIS-DSP `arm_rfft_fast_f32` uses the same unnormalised FFT convention as NumPy.

## Next steps

1. Run `app/` on a real phone (Expo Go) against the board; check the click, the vibration and the STOP button.
2. Wear it: confirm band power is bimodal (still tens of mg^2, walking >10^4), try simulated freezes, record
   labelled sessions from the port-7000 page, run `check_recording.py`.
3. Own recordings, then re-tune the amplitude thresholds -- on new recordings, never the ones reported from.
4. `device/detector/`: the C port, still the plan of record (ADR-0002), no longer on the demo path.
