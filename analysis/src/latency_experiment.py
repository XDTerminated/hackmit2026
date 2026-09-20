"""How to make the cue fire sooner, and what it costs in false alarms.

Problem: with a 4 s window the freeze index is dominated by whatever happened in the last
4 s. When someone walks and then freezes abruptly, the strong walking signal has to slide out
of the window before the index can rise, so the cue lags by 2-4 s. (Patients' gait usually
degrades before a freeze, which hides the problem in the patient datasets.)

Candidates:
  rect N s    plain window of N seconds (4 s was the v1 detector)
  ramp N s    N second window weighted linearly from 0 (oldest sample) to 1 (newest), so old
              walking counts for little while the frequency resolution of N seconds is kept
  ramp^2      the same with squared weights (even more emphasis on recent samples)

All use the frozen thresholds (freeze index > 1.056, band power > 178 mg^2; power is normalised
for the weighting) and the cue logic gate 5 s + hold 5 s, with debounce 2 or 1.

Usage: python src/latency_experiment.py [--healthy-dir DIR]
  --healthy-dir: folder of CSVs with columns acc_x, acc_y, acc_z [m/s^2], timestamp, label
                 (walking/standing/freezing) from healthy people simulating freezes. Not part of
                 this repo; without it only the patient datasets are scored.
"""

import argparse
import glob

import numpy as np
import pandas as pd
from scipy.signal import resample

from baseline_fi import SAMPLE_RATE_HZ, STEP_S, clean_dir, load_subject, window_features
from simulate_device import CueConfig, cue_logic, simulate_subject
from streaming_detector import DetectorParams

FI_TH, POWER_TH = DetectorParams().fi_threshold, DetectorParams().power_threshold
STEP = int(STEP_S * SAMPLE_RATE_HZ)
CANDIDATES = [("rect 4 s (v1)", 4, 0), ("rect 3 s", 3, 0), ("rect 2 s", 2, 0), ("rect 1.5 s", 1.5, 0),
              ("ramp 4 s (v2; v3 adds the stop rule)", 4, 1), ("ramp 3 s", 3, 1), ("ramp^2 4 s", 4, 2), ("ramp^2 3 s", 3, 2)]


_patients = {}   # (dataset, window, weighting) -> windowed segments; the two debounce settings share them


def patient_scores(dataset, win_s, ramp_power, cfg):
    key = (dataset, win_s, ramp_power)
    if key not in _patients:
        _patients[key] = [load_subject(path, int(win_s * SAMPLE_RATE_HZ), STEP, ramp_power)
                          for path in sorted(clean_dir(dataset).glob("*.csv"))]
    results = [simulate_subject(segments, FI_TH, POWER_TH, cfg) for segments in _patients[key]]
    caught = sum(r["detected"] for r in results) / sum(r["episodes"] for r in results)
    false_per_h = sum(r["fa"] for r in results) / sum(r["hours"] for r in results)
    latencies = [x for r in results for x in r["latencies"]]
    return f"{100 * caught:.0f}%", round(false_per_h), round(float(np.median(latencies)), 1)


def healthy_scores(folder, win_s, ramp_power, cfg):
    latencies, bouts, walk_on, walk_n = [], 0, 0, 0
    for path in sorted(glob.glob(folder + "/**/*.csv", recursive=True)):
        d = pd.read_csv(path)
        duration = (pd.to_datetime(d["timestamp"]).iloc[-1] - pd.to_datetime(d["timestamp"]).iloc[0]).total_seconds()
        n = int(duration * SAMPLE_RATE_HZ)
        if n < 10 * SAMPLE_RATE_HZ:
            continue
        acc = resample(d[["acc_x", "acc_y", "acc_z"]].to_numpy() * 1000 / 9.80665, n, axis=0)
        label = d["label"].to_numpy()[np.minimum((np.arange(n) * len(d) / n).astype(int), len(d) - 1)]
        fi, power, end_idx = window_features(np.linalg.norm(acc, axis=1), int(win_s * SAMPLE_RATE_HZ), STEP, ramp_power)
        cue = cue_logic(fi, power, FI_TH, POWER_TH, cfg)
        edges = np.concatenate([[0], np.flatnonzero(label[1:] != label[:-1]) + 1, [n]])
        for a, b in zip(edges[:-1], edges[1:]):
            if label[a] == "freezing" and b - a >= 4 * SAMPLE_RATE_HZ and a > 0 and label[a - 1] == "walking":
                bouts += 1
                hits = end_idx[cue & (end_idx >= a) & (end_idx < b)]
                if len(hits):
                    latencies.append((hits[0] - a) / SAMPLE_RATE_HZ)
        win = int(win_s * SAMPLE_RATE_HZ)
        walking_only = np.array([set(label[i - win + 1:i + 1]) == {"walking"} for i in end_idx])
        walk_on, walk_n = walk_on + cue[walking_only].sum(), walk_n + walking_only.sum()
    if not latencies:
        return f"0/{bouts}", None, None, f"{100 * walk_on / walk_n:.0f}%"
    return f"{len(latencies)}/{bouts}", round(float(np.median(latencies)), 1), round(max(latencies), 1), f"{100 * walk_on / walk_n:.0f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--healthy-dir")
    args = parser.parse_args()

    rows = []
    for name, win_s, ramp_power in CANDIDATES:
        for debounce in (2, 1):
            cfg = CueConfig("x", debounce=debounce, gate_lookback_s=5, hold_s=5)
            row = {"window": name, "debounce": debounce}
            if args.healthy_dir:
                row["healthy caught"], row["healthy latency s"], row["worst s"], row["cue while walking"] = \
                    healthy_scores(args.healthy_dir, win_s, ramp_power, cfg)
            for dataset in ("daphnet", "mendeley"):
                row[f"{dataset} caught"], row[f"{dataset} FA/h"], row[f"{dataset} latency s"] = \
                    patient_scores(dataset, win_s, ramp_power, cfg)
            rows.append(row)
            print(".", end="", flush=True)
    pd.set_option("display.width", 250)
    print("\n" + pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
