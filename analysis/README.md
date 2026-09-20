# analysis

Laptop-side Python: dataset cleaning, detector evaluation, and the sample-at-a-time reference
implementation that the firmware is checked against.

```
cd analysis
uv sync                          # or: pip install numpy pandas scipy scikit-learn joblib
uv run src/clean_daphnet.py      # needs ../data/daphnet/raw/, see the root README
uv run src/baseline_fi.py
```

Scripts find `data/` and `test_vectors/` relative to the repo root, so they work from any directory.

| script | what it does |
|---|---|
| `clean_daphnet.py` | ankle sensor only, repairs transmission glitches, drops non-experiment rows, splits into gap-free segments |
| `download_mendeley.py`, `clean_mendeley.py` | fetches the second dataset (3.9 GB); keeps one shank IMU (accel + gyro), converts counts to mg and deg/s, resamples 500 to 64 Hz |
| `baseline_fi.py` | Freeze Index detector, leave-one-subject-out evaluation, window-length comparison. `--dataset daphnet\|mendeley` |
| `simulate_device.py` | the on-device cue logic (debounce, walking gate, hold) on top of the detector. `--ramp 1` uses the current recency-weighted window (default 0 reproduces the original results). `--nested 0.9` checks the logic was not overfit; `--dataset mendeley --fixed-thresholds 1.056 178` runs the frozen detector on data it has never seen |
| `streaming_detector.py` | sample-at-a-time reference for the STM32 port. `--verify` checks it against the batch code, `--export` writes `../test_vectors/` |
| `check_recording.py` | validates a capture from `device/imu_stream`: sample rate, lost samples, gravity scale, clipping, still-vs-walking band power, and what the frozen detector does on it |
| `latency_experiment.py` | why the cue lagged 2-4 s after an abrupt freeze and what fixes it: window lengths and recency weighting, scored on latency and false alarms. Led to the weighted window now in the detector |
| `gyro_experiment.py` | what the gyroscope adds (turn veto, gyro-based freeze index), on the Mendeley data |
| `train_rf.py`, `calibration_experiment.py` | experiments that did **not** beat the baseline (random forest, per-user calibration); kept as evidence |

Both cleaned datasets share the columns `subject, run, segment, t_ms, acc_mag, freeze`, which is all the
evaluation scripts need. Always build windows within a `segment`, never across one.
