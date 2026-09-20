"""Can the false cue after a normal stop be removed without slowing the detector down?

In our own recordings every false cue so far is the same event: the wearer stops walking, the
walking power decays out of the window, and for a frame or two the freeze index drifts above its
threshold while there is still some power left. Three candidate fixes, scored on our recordings
(freezes caught, latency, false cues) and on both patient datasets (episodes, latency, false cues/h):

  higher freeze-index threshold   removes them, but slows every detection and loses patient episodes
  higher power threshold          does not generalise: one person's stop crosses the index threshold
                                  while power is still 18,000 mg^2, above another person's freezes
  stop veto                       ignore a window whose band power is below RATIO x the previous
                                  window's. In a stop, power collapses by half or more every 0.5 s;
                                  in a freeze it levels off.

All use the recency-weighted 4 s window and the cue logic gate 5 s + hold 5 s + debounce 2.
NOTE: the veto ratio (0.6) was chosen while looking at the two recordings it is scored on here. On
independent healthy recordings it changed nothing (no harm, no benefit shown), and on patients it
costs about 1.5% of episodes. It was adopted as the detector's default on that basis: provisional,
and the first thing to re-check when a new person is recorded.

Usage: python src/stop_veto_experiment.py
"""

import numpy as np
import pandas as pd

from baseline_fi import clean_dir, load_subject, summary_row, window_features
from evaluate_own import RAW_DIR, score_cues
from simulate_device import CueConfig, cue_logic, simulate_subject, stop_veto
from streaming_detector import DetectorParams

P = DetectorParams()
WIN, STEP, RAMP, RATE = P.window, P.step, P.ramp_power, P.sample_rate_hz
FI, POWER = P.fi_threshold, P.power_threshold   # the detector's thresholds; the candidates move one thing each
CUE = CueConfig("gate 5s + hold 5s + debounce 2", debounce=2, gate_lookback_s=5, hold_s=5)
CANDIDATES = [  # (name, freeze-index threshold, power threshold, veto ratio)
    ("no stop rule (v2)", FI, POWER, None),
    ("freeze index > 1.5", 1.5, POWER, None),
    ("freeze index > 1.75", 1.75, POWER, None),
    ("power > 2000", FI, 2000.0, None),
    ("stop veto 0.5", FI, POWER, 0.5),
    ("stop veto 0.6 (adopted, v3)", FI, POWER, 0.6),
    ("stop veto 0.7", FI, POWER, 0.7),
]


def cues_for(magnitude, fi_th, power_th, ratio):
    fi, power, end_idx = window_features(magnitude, WIN, STEP, RAMP)
    return cue_logic(fi, power, fi_th, power_th, CUE, stop_veto(power, ratio)), end_idx


def own_scores(fi_th, power_th, ratio):
    cells = []
    for path in sorted(RAW_DIR.glob("*.csv")):
        data = pd.read_csv(path)
        labels = data["label"].fillna("").to_numpy()
        cue, idx = cues_for(np.linalg.norm(data[["ax_mg", "ay_mg", "az_mg"]].to_numpy(), axis=1), fi_th, power_th, ratio)
        n_freezes, latencies, false = score_cues(labels, idx, cue, RATE)
        timing = f"{np.median(latencies):.1f} s (max {max(latencies):.1f})" if latencies else "none caught"
        cells.append(f"{len(latencies)}/{n_freezes}, {timing}, false {len(false)}")
    return cells


_patients = {}   # dataset -> every subject's windowed segments; the candidates only differ in thresholds


def patient_scores(dataset, fi_th, power_th, ratio):
    if dataset not in _patients:
        _patients[dataset] = [load_subject(path, WIN, STEP, RAMP) for path in sorted(clean_dir(dataset).glob("*.csv"))]
    row = summary_row([simulate_subject(segments, fi_th, power_th, CUE, [stop_veto(seg["power"], ratio) for seg in segments])
                       for segments in _patients[dataset]])
    return f"{row['episodes']}, {row['latency_s']:.1f} s, {row['false_cues/h']:.0f}/h"


def main():
    names = [p.stem.split("_", 2)[-1] for p in sorted(RAW_DIR.glob("*.csv"))]   # date_time_name.csv -> name
    rows = []
    for name, fi_th, power_th, ratio in CANDIDATES:
        row = {"detector": name}
        row.update(dict(zip(names, own_scores(fi_th, power_th, ratio))))
        for dataset in ("daphnet", "mendeley"):
            row[dataset] = patient_scores(dataset, fi_th, power_th, ratio)
        rows.append(row)
        print(".", end="", flush=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 60)
    print("\nown recordings: freezes caught, median latency (max), false cues | patients: episodes, latency, false cues/h")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
