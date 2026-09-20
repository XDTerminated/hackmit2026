"""Clean the Mendeley multimodal freezing-of-gait dataset into the same format as Daphnet.

Reads data/mendeley/raw/<patient>/task_N.txt (fetch with download_mendeley.py) and
writes one CSV per patient to data/mendeley/clean/. Only one shank IMU is kept:
the device is a single shin-worn sensor, so EEG, EMG, waist and arm are dropped.

Steps:
  1. Pick the shank sensor: left if it recorded, otherwise right. A sensor that
     was not worn is stored as all zeros.
  2. Convert raw MPU6050 counts to physical units. Both scales were inferred from
     the data: gravity reads ~8500 counts (8192 LSB/g, +-4 g range) and the
     protocol's quarter turns integrate to ~90 deg at 16.4 LSB/(deg/s) (+-2000 dps).
  3. Resample 500 Hz -> 64 Hz (exactly 16/125) to match Daphnet and the device.
  4. Split a recording into segments wherever its timestamps jump, so windows are
     never built across a gap.

Output columns:
  subject, run, segment, t_ms, acc_x, acc_y, acc_z, acc_mag [mg],
  gyr_x, gyr_y, gyr_z [deg/s], freeze (0/1), leg (L/R)
Axes are the sensor's own; in the sessions checked x points along the shank
(gravity). There is no "outside the experiment" label in this dataset.

Usage: python analysis/clean_mendeley.py
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]  # repo root
RAW_DIR = ROOT / "data" / "mendeley" / "raw"
OUT_DIR = ROOT / "data" / "mendeley" / "clean"

RAW_RATE_HZ, OUT_RATE_HZ = 500, 64
UP, DOWN = 16, 125                   # 500 * 16 / 125 = 64
ACC_COUNTS_PER_G = 8192
GYRO_COUNTS_PER_DPS = 16.4
MIN_SEGMENT_SAMPLES = 4 * OUT_RATE_HZ
MAX_GAP_S = 0.1

COL_TIME, COL_LABEL = 1, 60
SHANK_COLS = {"L": list(range(32, 38)), "R": list(range(39, 45))}  # acc xyz, gyro xyz
SIGNALS = ["acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z"]
AXES_ACC = SIGNALS[:3]


def contiguous_segments(seconds):
    """(start, end) row ranges between timestamp jumps (end exclusive)."""
    breaks = np.flatnonzero(np.abs(np.diff(seconds) - 1 / RAW_RATE_HZ) > MAX_GAP_S) + 1
    edges = np.concatenate([[0], breaks, [len(seconds)]])
    return list(zip(edges[:-1], edges[1:]))


def clean_task(path, subject, run, first_segment_id):
    raw = pd.read_csv(path, header=None, usecols=[COL_TIME, *SHANK_COLS["L"], *SHANK_COLS["R"], COL_LABEL])
    present = {leg: (raw[cols].to_numpy() != 0).any(axis=1).mean() for leg, cols in SHANK_COLS.items()}
    leg = "L" if present["L"] > 0.99 else "R"
    stats = dict(file=f"{subject}/{run}", raw_min=round(len(raw) / RAW_RATE_HZ / 60, 1), leg=leg,
                 present_L=round(present["L"], 3), present_R=round(present["R"], 3))
    if present[leg] <= 0.99:
        return None, {**stats, "leg": "none", "segments": 0}

    signals = raw[SHANK_COLS[leg]].to_numpy(float)
    signals[:, :3] *= 1000 / ACC_COUNTS_PER_G
    signals[:, 3:] /= GYRO_COUNTS_PER_DPS
    label = raw[COL_LABEL].to_numpy()
    seconds = pd.to_timedelta(raw[COL_TIME]).dt.total_seconds().to_numpy()
    # The time column is only used to find gaps; t_ms is rebuilt from the sample count.
    parts, segment_id = [], first_segment_id
    for start, end in contiguous_segments(seconds):
        resampled = resample_poly(signals[start:end], UP, DOWN, axis=0)
        n = len(resampled)
        if n < MIN_SEGMENT_SAMPLES:
            continue
        source_rows = np.minimum((np.arange(n) * DOWN / UP).round().astype(int), end - start - 1)
        part = pd.DataFrame(resampled, columns=SIGNALS)
        part.insert(0, "t_ms", ((seconds[start] - seconds[0]) * 1000 + np.arange(n) * 1000 / OUT_RATE_HZ).round().astype(int))
        part.insert(0, "segment", segment_id)
        part["freeze"] = (label[start:end][source_rows] == 1).astype(int)
        parts.append(part)
        segment_id += 1
    if not parts:
        return None, {**stats, "segments": 0}

    df = pd.concat(parts, ignore_index=True)
    df.insert(0, "run", run)
    df.insert(0, "subject", subject)
    df["acc_mag"] = np.linalg.norm(df[["acc_x", "acc_y", "acc_z"]].to_numpy(), axis=1)
    df["leg"] = leg
    df = df[["subject", "run", "segment", "t_ms", "acc_x", "acc_y", "acc_z", "acc_mag",
             "gyr_x", "gyr_y", "gyr_z", "freeze", "leg"]]
    numeric = ["acc_x", "acc_y", "acc_z", "acc_mag", "gyr_x", "gyr_y", "gyr_z"]
    df[numeric] = df[numeric].round(1)

    freeze = df["freeze"].to_numpy()
    stats.update(segments=segment_id - first_segment_id, kept_min=round(len(df) / OUT_RATE_HZ / 60, 1),
                 freeze_pct=round(100 * freeze.mean(), 1), episodes=int((np.diff(freeze, prepend=0) == 1).sum()),
                 gravity_mg=round(float(df["acc_mag"].median())), max_acc_mg=round(float(df[AXES_ACC].abs().max().max())))
    return df, stats


def main():
    patients = sorted(p for p in RAW_DIR.iterdir() if p.is_dir() and p.name.isdigit())  # skips the authors' Code/ folder
    if not patients:
        raise SystemExit(f"No data in {RAW_DIR}; run download_mendeley.py first")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_stats = []
    for patient in patients:
        subject = f"M{int(patient.name):02d}"
        runs, next_segment = [], 0
        for path in sorted(patient.rglob("task_*.txt")):
            # Patient 008 did two sessions, stored in sub-folders; both belong to the same subject.
            session = path.parent.name if path.parent != patient else ""
            run = f"{session}_{path.stem}".strip("_")
            df, stats = clean_task(path, subject, run, next_segment)
            all_stats.append(stats)
            if df is not None:
                next_segment += stats["segments"]
                runs.append(df)
        if runs:
            pd.concat(runs, ignore_index=True).to_csv(OUT_DIR / f"{subject}.csv", index=False)
        print(f"  {subject} done", flush=True)

    summary = pd.DataFrame(all_stats)
    pd.set_option("display.width", 200)
    print(summary.to_string(index=False))
    print(f"\nWrote {len(list(OUT_DIR.glob('M*.csv')))} subject files to {OUT_DIR}")
    print(f"Kept {summary.kept_min.sum():.0f} min, {int(summary.episodes.sum())} freeze episodes; "
          f"{(summary.segments == 0).sum()} task files had no usable shank sensor")


if __name__ == "__main__":
    main()
