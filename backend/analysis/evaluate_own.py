"""Score the detector on our own labelled recordings (data/own/raw/*.csv), bout by bout.

Recordings come from the board's diagnostics page (docs/recording-protocol.md): healthy volunteers,
labels walking / standing / freezing pressed live by an observer. For every recording and each
sensitivity preset this reports

  - each simulated freeze: caught or missed, and the time from the label to the cue
  - false cues: cues that start outside a freeze (and not in the few seconds after one, when the
    cue is simply still holding)
  - how often the detector is on, per label, and the band power per label

Labels are pressed by hand, so latencies are good to a few tenths of a second at best. These are
acted freezes: the numbers say whether the device works in the demo, not how it does on patients.

Usage: python analysis/evaluate_own.py [files...]        (default: every CSV in data/own/raw)
"""

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from detector import PRESETS, DetectorParams, StreamingDetector, run

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "own" / "raw"
HOLD_TAIL_S = 6        # a cue starting this soon after a freeze ends is carry-over, not a false cue


def bouts(labels):
    """(label, start, end) for each run of identical labels (end exclusive)."""
    edges = np.concatenate([[0], np.flatnonzero(labels[1:] != labels[:-1]) + 1, [len(labels)]])
    return [(labels[a], a, b) for a, b in zip(edges[:-1], edges[1:])]


def score_cues(labels, index, cue, rate):
    """One recording's cue output against its labels.

    index[i] is the sample at which frame i ends and cue[i] the cue state there. Returns (number of
    freeze bouts, latency in seconds of each one that was caught, sample index of each false cue).
    """
    freezes = [(a, b) for name, a, b in bouts(labels) if name == "freezing"]
    hits = [index[cue & (index >= a) & (index < b)] for a, b in freezes]
    latencies = [(h[0] - a) / rate for h, (a, _) in zip(hits, freezes) if len(h)]
    starts = index[cue & ~np.concatenate([[False], cue[:-1]])]
    false_cues = [s for s in starts if labels[s] != "freezing"
                  and not any(0 <= s - end < HOLD_TAIL_S * rate for _, end in freezes)]
    return len(freezes), latencies, false_cues


def evaluate(path, params):
    rate = params.sample_rate_hz
    data = pd.read_csv(path)
    labels = data["label"].fillna("").to_numpy()
    frames = run(StreamingDetector(params), axes=data[["ax_mg", "ay_mg", "az_mg"]].to_numpy())
    index, cue = frames["sample_index"].to_numpy(), frames["cue_on"].to_numpy()

    n_freezes, latencies, false_cues = score_cues(labels, index, cue, rate)

    frames["label"] = labels[index]
    per_label = frames[frames["label"] != ""].groupby("label").agg(
        frames=("cue_on", "size"), cue_on=("cue_on", "mean"), median_power=("total_power", "median"))
    return dict(freezes=n_freezes, missed=n_freezes - len(latencies), latencies=latencies,
                false_cues=[(s / rate, labels[s] or "unlabelled") for s in false_cues],
                minutes=len(data) / rate / 60, per_label=per_label)


def main():
    files = [Path(f) for f in sys.argv[1:]] or sorted(RAW_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(f"No recordings in {RAW_DIR}; see docs/recording-protocol.md")

    for preset, overrides in PRESETS.items():
        params = replace(DetectorParams(), **overrides)
        print(f"\n=== {preset} ===")
        all_latencies, n_freezes, n_missed, n_false, minutes = [], 0, 0, 0, 0.0
        for path in files:
            r = evaluate(path, params)
            caught = r["freezes"] - r["missed"]
            latency = (f"latency median {np.median(r['latencies']):.1f} s, range "
                       f"{min(r['latencies']):.1f}-{max(r['latencies']):.1f} s") if r["latencies"] else "no latency"
            print(f"{path.name}: {r['minutes']:.1f} min, freezes caught {caught}/{r['freezes']}, {latency}, "
                  f"false cues {len(r['false_cues'])}")
            for t, label in r["false_cues"]:
                print(f"    false cue at {t:.0f} s while {label}")
            if preset == "balanced":
                print(r["per_label"].round(2).to_string().replace("\n", "\n    ").join(["    ", ""]))
            all_latencies += r["latencies"]
            n_freezes, n_missed = n_freezes + r["freezes"], n_missed + r["missed"]
            n_false, minutes = n_false + len(r["false_cues"]), minutes + r["minutes"]
        if len(files) > 1 and all_latencies:
            print(f"ALL: caught {n_freezes - n_missed}/{n_freezes}, median latency {np.median(all_latencies):.1f} s, "
                  f"{n_false} false cues in {minutes:.0f} min ({60 * n_false / minutes:.0f} per hour)")


if __name__ == "__main__":
    main()
