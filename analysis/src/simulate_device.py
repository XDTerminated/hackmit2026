"""Simulate the on-device cue logic on Daphnet and measure what it does to false alarms.

baseline_fi.py scores the raw per-window detector. A real device wraps that in a
small state machine, which is what the wearer actually hears:

  debounce    fire only after N consecutive positive windows
  walk gate   fire only if the user was walking within the last few seconds
              (a freeze interrupts walking; fidgeting while standing does not count).
              The gate controls when a cue may start, not whether it continues.
  hold        once started, the metronome plays for at least H seconds and keeps
              playing while the detector stays positive
  refractory  after the metronome stops, ignore triggers for R seconds

Freeze-index and power thresholds are tuned leave-one-subject-out exactly as in
baseline_fi.py. The logic parameters are fixed per configuration and were not
tuned per fold, so compare configurations rather than trusting a single number.

cue_logic() is written as a per-frame loop with scalar state on purpose: it is
the reference for the STM32 port.

With --nested the cue logic itself is also chosen inside each fold, which is the
honest check that the configuration was not picked to fit the test subjects.

Usage: python src/simulate_device.py [--window 4] [--min-spec X] [--nested 0.9]
           [--dataset daphnet|mendeley] [--fixed-thresholds FI POWER] [--per-subject "CUE LOGIC NAME"]
"""

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from baseline_fi import (DATASETS, FI_GRID, POWER_GRID, SAMPLE_RATE_HZ, STEP_S, clean_dir, grid_counts, load_subject,
                         loso_cell, score_subject, summary_row)

WALK_LOCO_POWER_MG2 = 10_000  # locomotion-band power is ~10-30 mg^2 standing, >10^4 walking


@dataclass
class CueConfig:
    name: str
    debounce: int = 1          # frames
    gate_lookback_s: float = 0  # 0 disables the walking gate
    gate_min_walk_s: float = 1
    hold_s: float = 0
    refractory_s: float = 0


CONFIGS = [
    CueConfig("raw detector"),
    CueConfig("debounce 2", debounce=2),
    CueConfig("hold 5s", hold_s=5),
    CueConfig("hold 8s", hold_s=8),
    CueConfig("hold 5s + refractory 5s", hold_s=5, refractory_s=5),
    CueConfig("gate 5s", gate_lookback_s=5),
    CueConfig("gate 10s", gate_lookback_s=10),
    CueConfig("gate 5s + hold 5s", gate_lookback_s=5, hold_s=5),
    CueConfig("gate 5s + hold 5s + debounce 2", debounce=2, gate_lookback_s=5, hold_s=5),
    CueConfig("gate 5s + hold 8s + debounce 2", debounce=2, gate_lookback_s=5, hold_s=8),
    CueConfig("gate 5s + hold 5s + debounce 3", debounce=3, gate_lookback_s=5, hold_s=5),
]


NESTED_GRID = [
    CueConfig(f"gate {g}s + hold {h}s + debounce {d}", debounce=d, gate_lookback_s=g, hold_s=h)
    for d in (1, 2, 3) for g in (0, 5, 10) for h in (0, 5, 8)
]


def stop_veto(power, ratio):
    """True where band power is below ratio x the previous window's: a stop in progress.

    When the wearer simply stops walking, power collapses by half or more every 0.5 s, and on the
    way down the freeze index drifts above its threshold for a frame or two. In a freeze the
    power levels off instead. ratio 0 (or None) disables the rule. See stop_veto_experiment.py.
    """
    if not ratio:
        return None
    previous = np.concatenate([[power[0]], power[:-1]])
    return power < ratio * previous


def cue_logic(fi, power, fi_th, power_th, cfg, veto=None):
    """Run the cue state machine over one segment's frames. Returns cue on/off per frame.

    veto is an optional boolean array; a vetoed frame never counts as positive
    (used by gyro_experiment.py to suppress detections while the wearer is turning).
    """
    frames = lambda seconds: int(round(seconds / STEP_S))
    lookback, min_walk = frames(cfg.gate_lookback_s), frames(cfg.gate_min_walk_s)
    hold, refractory = frames(cfg.hold_s), frames(cfg.refractory_s)

    cue = np.zeros(len(fi), bool)
    cue_on = False
    consecutive = 0          # positive frames in a row
    walk_history = []        # one flag per recent frame, newest last, at most `lookback` long
    hold_end = 0             # cue may not stop before this frame
    blocked_until = 0        # refractory
    for i in range(len(fi)):
        positive = fi[i] > fi_th and power[i] > power_th and not (veto is not None and veto[i])
        consecutive = consecutive + 1 if positive else 0
        armed = lookback == 0 or sum(walk_history) >= min_walk

        if cue_on:
            # Once playing, the gate no longer applies: a long freeze has no recent walking.
            cue_on = positive or i < hold_end
            if not cue_on:
                blocked_until = i + refractory
        if not cue_on and positive and armed and consecutive >= cfg.debounce and i >= blocked_until:
            cue_on = True
            hold_end = i + hold
        cue[i] = cue_on

        walk_history.append(power[i] / (1 + fi[i]) > WALK_LOCO_POWER_MG2)  # locomotion-band power
        if len(walk_history) > lookback:
            walk_history.pop(0)
    return cue


def simulate_subject(segments, fi_th, power_th, cfg, vetoes=None):
    """score_subject() results for one subject under one cue configuration."""
    vetoes = vetoes or [None] * len(segments)
    cues = [cue_logic(seg["fi"], seg["power"], fi_th, power_th, cfg, veto) for seg, veto in zip(segments, vetoes)]
    return score_subject(segments, cues)


def nested_selection(data, fold_thresholds, min_detected):
    """Pick the cue logic inside each fold, using the training subjects only.

    For each held-out subject: among NESTED_GRID, take the configuration with the
    fewest false cues per hour on the other nine subjects that still catches at
    least min_detected of their freeze episodes, then score it on the held-out one.
    """
    subjects = list(data)
    cache = {}

    def result(subject, thresholds, cfg):
        key = (subject, thresholds, cfg.name)
        if key not in cache:
            cache[key] = simulate_subject(data[subject], *thresholds, cfg)
        return cache[key]

    held_out_results, chosen = [], []
    for held_out in subjects:
        th = fold_thresholds[held_out]
        best, best_fa = None, np.inf
        for cfg in NESTED_GRID:
            train = [result(s, th, cfg) for s in subjects if s != held_out]
            detected = sum(r["detected"] for r in train) / sum(r["episodes"] for r in train)
            fa = sum(r["fa"] for r in train) / sum(r["hours"] for r in train)
            if detected >= min_detected and fa < best_fa:
                best, best_fa = cfg, fa
        chosen.append(best.name)
        held_out_results.append(result(held_out, th, best))
    return held_out_results, chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--window", type=float, default=4, help="window length in seconds")
    parser.add_argument("--min-spec", type=float, default=None,
                        help="tune thresholds for max sensitivity at this raw specificity (default: balanced accuracy)")
    parser.add_argument("--nested", type=float, metavar="MIN_DETECTED", default=None,
                        help="also choose the cue logic inside each fold: fewest false cues on the training "
                             "subjects while catching at least this fraction of their episodes (e.g. 0.9)")
    parser.add_argument("--dataset", choices=DATASETS, default="daphnet")
    parser.add_argument("--fixed-thresholds", type=float, nargs=2, metavar=("FI", "POWER"), default=None,
                        help="use these detector thresholds for every subject instead of tuning them; "
                             "with a dataset the thresholds never saw, this is an external validation")
    parser.add_argument("--ramp", type=int, default=0,
                        help="recency weighting of the window: 0 = none (original detector), 1 = linear ramp (current detector)")
    parser.add_argument("--stop-veto", type=float, default=0.0, metavar="RATIO",
                        help="ignore windows whose power is below RATIO x the previous window's "
                             "(0 = off, the original detector; 0.6 = current detector)")
    parser.add_argument("--per-subject", metavar="CUE_LOGIC", default=None,
                        help="also print per-subject results for the named cue logic")
    args = parser.parse_args()

    win, step = int(args.window * SAMPLE_RATE_HZ), int(STEP_S * SAMPLE_RATE_HZ)
    files = sorted(clean_dir(args.dataset).glob("*.csv"))
    if not files:
        raise SystemExit(f"No cleaned data in {clean_dir(args.dataset)}; run clean_{args.dataset}.py first")
    data = {f.stem: load_subject(f, win, step, args.ramp) for f in files}
    subjects = list(data)

    grid = {s: grid_counts(data[s], 1) for s in subjects}
    thresholds = {}
    for held_out in subjects:
        i, j = loso_cell(grid, held_out, args.min_spec)
        thresholds[held_out] = (FI_GRID[i], POWER_GRID[j])
    if args.fixed_thresholds:
        thresholds = {s: tuple(args.fixed_thresholds) for s in subjects}

    vetoes = {s: [stop_veto(seg["power"], args.stop_veto) for seg in data[s]] for s in subjects}
    rows = [summary_row([simulate_subject(data[s], *thresholds[s], cfg, vetoes[s]) for s in subjects],
                        **{"cue logic": cfg.name})
            for cfg in CONFIGS]
    if args.nested is not None:
        results, chosen = nested_selection(data, thresholds, args.nested)
        rows.append(summary_row(results, **{"cue logic": f"NESTED (>= {args.nested:.0%} of training episodes)"}))

    pd.set_option("display.width", 200)
    tuning = (f"fixed at FI > {args.fixed_thresholds[0]:g}, power > {args.fixed_thresholds[1]:g}" if args.fixed_thresholds
              else "tuned LOSO for " + ("balanced accuracy" if args.min_spec is None else f"raw specificity >= {args.min_spec}"))
    print(f"{args.dataset}, window {args.window:g} s, ramp {args.ramp}, stop veto {args.stop_veto:g}, thresholds {tuning}")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    if args.per_subject:
        cfg = next(c for c in CONFIGS if c.name == args.per_subject)
        per_subject = [summary_row([simulate_subject(data[s], *thresholds[s], cfg, vetoes[s])], subject=s)
                       for s in subjects]
        print()
        print(f"Per subject, cue logic: {cfg.name}")
        print(pd.DataFrame(per_subject).to_string(index=False, float_format=lambda v: f"{v:.2f}", na_rep="-"))
    if args.nested is not None:
        print("\nCue logic chosen in each fold:")
        for subject, name in zip(subjects, chosen):
            print(f"  {subject}: {name}")


if __name__ == "__main__":
    main()
