"""Clean the Daphnet Freezing of Gait dataset for an ankle-worn detector.

Reads data/daphnet/raw/S<ss>R<rr>.txt and writes one CSV per subject to data/daphnet/clean/.

Cleaning steps:
  1. Keep only the ankle (shank) accelerometer; thigh and trunk are dropped.
  2. Repair transmission glitches: samples where any ankle axis exceeds
     SPIKE_MG (the sensor clips near +/-5000 mg, so anything far beyond that is
     corrupt) are replaced by linear interpolation between valid neighbours.
  3. Drop label-0 rows (not part of the experiment).
  4. Give each contiguous stretch of experiment data a segment id, so that
     windows are never built across a time jump. Segments too short to hold a
     single analysis window are dropped.
  5. Add the orientation-independent acceleration magnitude.

Output columns:
  subject, run, segment, t_ms, acc_f, acc_v, acc_l, acc_mag, freeze
  (acc_* in milli-g, freeze is 0/1, segment is unique within a subject)

Usage: python src/clean_daphnet.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # repo root
RAW_DIR = ROOT / "data" / "daphnet" / "raw"
OUT_DIR = ROOT / "data" / "daphnet" / "clean"

SAMPLE_RATE_HZ = 64
SPIKE_MG = 6000  # sensor saturates around +/-5000 mg
MIN_SEGMENT_SAMPLES = 4 * SAMPLE_RATE_HZ  # one 4 s Freeze Index window

COL_TIME = 0
COLS_ANKLE = [1, 2, 3]  # forward, vertical, lateral
COL_LABEL = 10
AXES = ["acc_f", "acc_v", "acc_l"]


def repair_spikes(ankle):
    """Interpolate over samples where any axis is beyond SPIKE_MG.

    A glitch corrupts the whole sample, not just the axis that went out of
    range, so all three axes are replaced. Returns (repaired, n_bad).
    """
    bad = (np.abs(ankle) > SPIKE_MG).any(axis=1)
    if not bad.any():
        return ankle, 0
    idx = np.arange(len(ankle))
    repaired = ankle.copy()
    for axis in range(ankle.shape[1]):
        repaired[bad, axis] = np.interp(idx[bad], idx[~bad], ankle[~bad, axis])
    return repaired, int(bad.sum())


def contiguous_segments(mask):
    """Return (start, end) index pairs for each run of True in mask (end exclusive)."""
    edges = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def clean_run(path, first_segment_id):
    """Clean one recording. Returns (DataFrame, stats dict)."""
    raw = np.loadtxt(path)
    subject, run = path.stem[:3], path.stem[3:]

    # Repair before dropping label-0 rows so interpolation sees true neighbours.
    ankle, n_spikes = repair_spikes(raw[:, COLS_ANKLE])
    label = raw[:, COL_LABEL].astype(int)

    parts = []
    n_short = 0
    segment_id = first_segment_id
    for start, end in contiguous_segments(label > 0):
        if end - start < MIN_SEGMENT_SAMPLES:
            n_short += 1
            continue
        part = pd.DataFrame(ankle[start:end], columns=AXES)
        part.insert(0, "t_ms", raw[start:end, COL_TIME].astype(int))
        part.insert(0, "segment", segment_id)
        part["freeze"] = (label[start:end] == 2).astype(int)
        parts.append(part)
        segment_id += 1

    df = pd.concat(parts, ignore_index=True)
    df.insert(0, "run", run)
    df.insert(0, "subject", subject)
    df["acc_mag"] = np.linalg.norm(df[AXES].to_numpy(), axis=1)
    df = df[["subject", "run", "segment", "t_ms", *AXES, "acc_mag", "freeze"]]
    df[[*AXES, "acc_mag"]] = df[[*AXES, "acc_mag"]].round(1)

    stats = {
        "file": path.stem,
        "raw_rows": len(raw),
        "kept_rows": len(df),
        "spikes_fixed": n_spikes,
        "segments": segment_id - first_segment_id,
        "short_dropped": n_short,
        "freeze_pct": round(100 * df["freeze"].mean(), 1),
    }
    return df, stats


def main():
    files = sorted(RAW_DIR.glob("S*R*.txt"))
    if not files:
        raise SystemExit(f"No dataset files found in {RAW_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_stats = []
    subjects = sorted({f.stem[:3] for f in files})
    for subject in subjects:
        runs = []
        next_segment = 0
        for path in [f for f in files if f.stem.startswith(subject)]:
            df, stats = clean_run(path, next_segment)
            next_segment += stats["segments"]
            runs.append(df)
            all_stats.append(stats)
        pd.concat(runs, ignore_index=True).to_csv(OUT_DIR / f"{subject}.csv", index=False)

    summary = pd.DataFrame(all_stats)
    print(summary.to_string(index=False))
    print(f"\nWrote {len(subjects)} subject files to {OUT_DIR}")
    print(f"Rows kept: {summary.kept_rows.sum():,} of {summary.raw_rows.sum():,}; "
          f"spike samples repaired: {summary.spikes_fixed.sum()}")


if __name__ == "__main__":
    main()
