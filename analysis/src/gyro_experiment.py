"""What does the gyroscope add? Two experiments on the Mendeley shank data.

Daphnet has no gyro, so this is the only real-patient data we have for the question.

1. Turn veto. Turning makes the accelerometer detector fire falsely, but freezes
   also tend to happen during turns. The idea: in a real freeze the feet are
   stuck, so the shank is not actually rotating about the vertical, whereas in a
   normal turn it is. A window is vetoed when the mean yaw rate over its last
   YAW_WINDOW_S seconds exceeds a limit. Yaw rate is the gyro vector projected on
   the gravity direction (from low-passed accel), so it does not depend on how
   the sensor is mounted. Accel thresholds are the frozen Daphnet ones.

2. Freeze index from the gyro instead of the accel, thresholds tuned
   leave-one-subject-out within Mendeley for both. The gyro magnitude is NOT
   usable here: rotation oscillates around zero, so taking the magnitude rectifies
   it and doubles the step frequency into the freeze band (accel magnitude is safe
   because gravity keeps it away from zero). Instead band powers are summed over
   the three axes, which is just as independent of sensor orientation.

Usage: python src/gyro_experiment.py
"""

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

from baseline_fi import (FI_GRID, POWER_GRID, SAMPLE_RATE_HZ, STEP_S, clean_dir, grid_counts, label_windows,
                         loso_cell, summary_row, window_features)
from simulate_device import CueConfig, simulate_subject
from streaming_detector import DetectorParams

WIN, STEP = 4 * SAMPLE_RATE_HZ, int(STEP_S * SAMPLE_RATE_HZ)
FROZEN_THRESHOLDS = (DetectorParams().fi_threshold, DetectorParams().power_threshold)   # tuned on Daphnet only
CUE = CueConfig("gate 5s + hold 5s + debounce 2", debounce=2, gate_lookback_s=5, hold_s=5)
RAW = CueConfig("raw detector")
GRAVITY_SMOOTH_S = 2.0
YAW_WINDOW_S = 1.0
YAW_LIMITS_DPS = [None, 80, 60, 40, 30, 20]
GYRO_POWER_GRID = np.concatenate([[0], np.round(np.logspace(0, 4.5, 33), 1)])  # (deg/s)^2


def yaw_rate(acc, gyr):
    """Rotation rate about the vertical in deg/s, per sample, signed."""
    gravity = uniform_filter1d(acc, int(GRAVITY_SMOOTH_S * SAMPLE_RATE_HZ), axis=0)
    gravity /= np.linalg.norm(gravity, axis=1, keepdims=True) + 1e-9
    return (gyr * gravity).sum(axis=1)


def summed_axis_features(signals):
    """Freeze index and total power with band powers summed over the columns of signals."""
    loco = freeze = 0
    for axis in signals.T:
        fi, power, _ = window_features(axis, WIN, STEP)
        loco = loco + power / (1 + fi)
        freeze = freeze + power * fi / (1 + fi)
    return freeze / np.maximum(loco, 1e-9), loco + freeze


def load_subject(path):
    segments = []
    for _, seg in pd.read_csv(path).groupby("segment"):
        freeze = seg["freeze"].to_numpy().astype(bool)
        acc = seg[["acc_x", "acc_y", "acc_z"]].to_numpy()
        gyr = seg[["gyr_x", "gyr_y", "gyr_z"]].to_numpy()
        fi, power, end_idx = window_features(seg["acc_mag"].to_numpy(), WIN, STEP)
        gyro_mag_fi, gyro_mag_power, _ = window_features(np.linalg.norm(gyr, axis=1), WIN, STEP)
        gyro_fi, gyro_power = summed_axis_features(gyr)
        acc3_fi, acc3_power = summed_axis_features(acc)
        # |mean| rather than mean|.|: leg tremor in a freeze wobbles both ways and averages out.
        smooth_yaw = uniform_filter1d(yaw_rate(acc, gyr), int(YAW_WINDOW_S * SAMPLE_RATE_HZ), origin=0)
        lag = int(YAW_WINDOW_S * SAMPLE_RATE_HZ) // 2  # centre the average on the last YAW_WINDOW_S seconds
        yaw = np.abs(smooth_yaw[np.maximum(end_idx - lag, 0)])
        segments.append(dict(fi=fi, power=power, gyro_fi=gyro_fi, gyro_power=gyro_power, yaw=yaw,
                             gyro_mag_fi=gyro_mag_fi, gyro_mag_power=gyro_mag_power,
                             acc3_fi=acc3_fi, acc3_power=acc3_power,
                             end_idx=end_idx, freeze=freeze, **label_windows(freeze, end_idx)))
    return segments


def main():
    files = sorted(clean_dir("mendeley").glob("*.csv"))
    if not files:
        raise SystemExit("No cleaned Mendeley data; run download_mendeley.py then clean_mendeley.py")
    data = {f.stem: load_subject(f) for f in files}
    subjects = list(data)
    pd.set_option("display.width", 200)
    show = lambda rows: print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    # How fast is the shank turning when the accel detector is right vs wrong?
    fi, power, yaw, y = (np.concatenate([s[k] for subj in subjects for s in data[subj]]) for k in ("fi", "power", "yaw", "y"))
    positive = (fi > FROZEN_THRESHOLDS[0]) & (power > FROZEN_THRESHOLDS[1])
    print("Yaw rate (deg/s) of accel-positive windows, percentiles 25/50/75/90:")
    print("  true positives :", np.percentile(yaw[positive & y], [25, 50, 75, 90]).round(1))
    print("  false positives:", np.percentile(yaw[positive & ~y], [25, 50, 75, 90]).round(1))

    print(f"\n1. Turn veto, frozen Daphnet thresholds, {len(subjects)} Mendeley subjects")
    rows = []
    for cfg in (RAW, CUE):
        for limit in YAW_LIMITS_DPS:
            vetoes = {s: [seg["yaw"] > limit for seg in data[s]] if limit else None for s in subjects}
            name = f"{cfg.name}, " + (f"veto yaw > {limit} dps" if limit else "no veto")
            rows.append(summary_row([simulate_subject(data[s], *FROZEN_THRESHOLDS, cfg, vetoes[s]) for s in subjects],
                                    **{"cue logic": name}))
    show(rows)

    print("\n2. Accel vs gyro freeze index, thresholds tuned leave-one-subject-out within Mendeley")
    rows = []
    for label, fi_key, power_key, power_grid in (
            ("accel magnitude (the device detector)", "fi", "power", POWER_GRID),
            ("accel, 3 axes summed", "acc3_fi", "acc3_power", POWER_GRID),
            ("gyro, 3 axes summed", "gyro_fi", "gyro_power", GYRO_POWER_GRID),
            ("gyro magnitude (flawed, see docstring)", "gyro_mag_fi", "gyro_mag_power", GYRO_POWER_GRID)):
        view = {s: [{**seg, "fi": seg[fi_key], "power": seg[power_key]} for seg in data[s]] for s in subjects}
        counts = {s: grid_counts(view[s], 1, FI_GRID, power_grid) for s in subjects}
        results = []
        for held_out in subjects:
            i, j = loso_cell(counts, held_out)
            results.append(simulate_subject(view[held_out], FI_GRID[i], power_grid[j], RAW))
        rows.append(summary_row(results, **{"cue logic": f"{label}, raw detector"}))
    show(rows)


if __name__ == "__main__":
    main()
