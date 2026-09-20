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
NOTE: the veto ratio was chosen while looking at the two recordings it is scored on here. It is a
candidate, not a result, until it has been checked on a person it has never seen.

Usage: python src/stop_veto_experiment.py
"""

import numpy as np
import pandas as pd

from baseline_fi import clean_dir, label_windows, score_subject, summary_row, window_features
from evaluate_own import HOLD_TAIL_S, RAW_DIR, bouts
from simulate_device import CueConfig, cue_logic

WIN, STEP, RAMP, RATE = 256, 32, 1, 64
CUE = CueConfig("gate 5s + hold 5s + debounce 2", debounce=2, gate_lookback_s=5, hold_s=5)
CANDIDATES = [  # (name, freeze-index threshold, power threshold, veto ratio)
    ("current detector", 1.056, 178.0, None),
    ("freeze index > 1.5", 1.5, 178.0, None),
    ("freeze index > 1.75", 1.75, 178.0, None),
    ("power > 2000", 1.056, 2000.0, None),
    ("stop veto 0.5", 1.056, 178.0, 0.5),
    ("stop veto 0.6", 1.056, 178.0, 0.6),
    ("stop veto 0.7", 1.056, 178.0, 0.7),
]


def stop_veto(power, ratio):
    """True where band power is still collapsing: a stop in progress, not a freeze."""
    if ratio is None:
        return None
    previous = np.concatenate([[power[0]], power[:-1]])
    return power < ratio * previous


def cues_for(magnitude, fi_th, power_th, ratio):
    fi, power, end_idx = window_features(magnitude, WIN, STEP, RAMP)
    return cue_logic(fi, power, fi_th, power_th, CUE, stop_veto(power, ratio)), end_idx


def own_scores(fi_th, power_th, ratio):
    cells = []
    for path in sorted(RAW_DIR.glob("*.csv")):
        data = pd.read_csv(path)
        labels = data["label"].fillna("").to_numpy()
        cue, idx = cues_for(np.linalg.norm(data[["ax_mg", "ay_mg", "az_mg"]].to_numpy(), axis=1), fi_th, power_th, ratio)
        freezes = [(a, b) for name, a, b in bouts(labels) if name == "freezing"]
        hits = [idx[cue & (idx >= a) & (idx < b)] for a, b in freezes]
        latencies = [(h[0] - a) / RATE for h, (a, _) in zip(hits, freezes) if len(h)]
        starts = idx[cue & ~np.concatenate([[False], cue[:-1]])]
        false = [s for s in starts if labels[s] != "freezing"
                 and not any(0 <= s - end < HOLD_TAIL_S * RATE for _, end in freezes)]
        cells.append(f"{len(latencies)}/{len(freezes)}, {np.median(latencies):.1f} s (max {max(latencies):.1f}), false {len(false)}")
    return cells


def patient_scores(dataset, fi_th, power_th, ratio):
    results = []
    for path in sorted(clean_dir(dataset).glob("*.csv")):
        segments, cues = [], []
        for _, seg in pd.read_csv(path).groupby("segment"):
            freeze = seg["freeze"].to_numpy().astype(bool)
            cue, idx = cues_for(seg["acc_mag"].to_numpy(), fi_th, power_th, ratio)
            segments.append(dict(end_idx=idx, freeze=freeze, **label_windows(freeze, idx)))
            cues.append(cue)
        results.append(score_subject(segments, cues))
    row = summary_row(results)
    return f"{row['episodes']}, {row['latency_s']:.1f} s, {row['false_cues/h']:.0f}/h"


def main():
    names = [p.stem.split("_", 2)[2] for p in sorted(RAW_DIR.glob("*.csv"))]
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
