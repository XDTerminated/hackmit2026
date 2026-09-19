"""Does per-user calibration reduce Freeze Index false alarms?

The first --cal-min minutes of each subject's recording are treated as a
calibration session; every method is scored on the remainder only.

  global      thresholds tuned on the other nine subjects (the baseline_fi.py setup)
  normalized  as global, but each subject's freeze index and power are first
              divided by their own median over freeze-free walking windows of the
              calibration session. This is what a device could do with a short
              supervised calibration walk: no freezes needed.
  personal    thresholds tuned on the subject's own calibration session. Needs
              labelled freezes from the user, so it is an upper bound rather than
              a realistic mode. Falls back to global when the session has none.

Usage: python src/calibration_experiment.py [--cal-min 5] [--window 4] [--debounce N] [--min-spec X]
"""

import argparse

import numpy as np
import pandas as pd

from baseline_fi import (CLEAN_DIR, FI_GRID, POWER_GRID, SAMPLE_RATE_HZ, STEP_S, best_cell, confusion, detect,
                         event_metrics, grid_counts, load_subject, rate)

WALK_POWER_MG2 = 178  # windows above this count as walking when computing the user's reference
NORM_POWER_GRID = np.concatenate([[0], np.round(np.logspace(-3, 1, 33), 4)])
METHODS = ["global", "normalized", "personal"]


def slice_segment(seg, a, b, win):
    """Windows a..b of a segment, with the sample-level freeze array cut to match."""
    lo, hi = seg["end_idx"][a] - win + 1, seg["end_idx"][b - 1] + 1
    out = {k: seg[k][a:b] for k in ("fi", "power", "y", "on_zone", "off_zone")}
    out["end_idx"] = seg["end_idx"][a:b] - lo
    out["freeze"] = seg["freeze"][lo:hi]
    return out


def split_chronological(segments, n_cal, win):
    """Split a subject's segments into (first n_cal windows, the rest)."""
    cal, test = [], []
    for seg in segments:
        n = len(seg["y"])
        take = min(max(n_cal, 0), n)
        if take:
            cal.append(slice_segment(seg, 0, take, win))
        if take < n:
            test.append(slice_segment(seg, take, n, win))
        n_cal -= n
    return cal, test


def normalize(segments, fi_ref, power_ref):
    return [{**s, "fi": s["fi"] / fi_ref, "power": s["power"] / power_ref} for s in segments]


def walking_reference(cal):
    """Median freeze index and power over freeze-free walking windows."""
    fi = np.concatenate([s["fi"] for s in cal])
    power = np.concatenate([s["power"] for s in cal])
    walking = (power > WALK_POWER_MG2) & ~np.concatenate([s["y"] for s in cal])
    return np.median(fi[walking]), np.median(power[walking])


def score(segments, fi_th, power_th, debounce, fi_grid, power_grid):
    """Tolerant/strict confusion counts and event metrics at fixed thresholds."""
    pos, n = grid_counts(segments, debounce, fi_grid, power_grid)
    i, j = np.flatnonzero(fi_grid == fi_th)[0], np.flatnonzero(power_grid == power_th)[0]
    tol = np.array([c[i, j] for c in confusion(pos, n, tolerant=True)])
    n_ep, n_det, _, _, n_fa = event_metrics(
        segments, [detect(s["fi"], s["power"], fi_th, power_th, debounce) for s in segments])
    return dict(tol=tol, episodes=n_ep, detected=n_det, fa=n_fa)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cal-min", type=float, default=5, help="calibration session length in minutes")
    parser.add_argument("--window", type=float, default=4, help="window length in seconds")
    parser.add_argument("--debounce", type=int, default=1)
    parser.add_argument("--min-spec", type=float, default=None)
    args = parser.parse_args()

    win, step = int(args.window * SAMPLE_RATE_HZ), int(STEP_S * SAMPLE_RATE_HZ)
    n_cal = int(args.cal_min * 60 / STEP_S)
    files = sorted(CLEAN_DIR.glob("S*.csv"))
    if not files:
        raise SystemExit(f"No cleaned data in {CLEAN_DIR}; run clean_daphnet.py first")

    subjects, full, full_norm, cal, test, test_norm = [], {}, {}, {}, {}, {}
    for f in files:
        s = f.stem
        subjects.append(s)
        full[s] = load_subject(f, win, step)
        cal[s], test[s] = split_chronological(full[s], n_cal, win)
        ref = walking_reference(cal[s])
        full_norm[s], test_norm[s] = normalize(full[s], *ref), normalize(test[s], *ref)

    counts = {s: grid_counts(full[s], args.debounce) for s in subjects}
    counts_norm = {s: grid_counts(full_norm[s], args.debounce, FI_GRID, NORM_POWER_GRID) for s in subjects}

    def loso_thresholds(counts, held_out, power_grid):
        pos = sum(counts[s][0] for s in subjects if s != held_out)
        n = sum(counts[s][1] for s in subjects if s != held_out)
        i, j = best_cell(pos, n, args.min_spec)
        return FI_GRID[i], power_grid[j]

    results = {m: {} for m in METHODS}
    for s in subjects:
        glob = loso_thresholds(counts, s, POWER_GRID)
        results["global"][s] = score(test[s], *glob, args.debounce, FI_GRID, POWER_GRID)

        norm = loso_thresholds(counts_norm, s, NORM_POWER_GRID)
        results["normalized"][s] = score(test_norm[s], *norm, args.debounce, FI_GRID, NORM_POWER_GRID)

        personal = glob
        if any(seg["y"].any() for seg in cal[s]):
            i, j = best_cell(*grid_counts(cal[s], args.debounce), args.min_spec)
            personal = (FI_GRID[i], POWER_GRID[j])
        results["personal"][s] = score(test[s], *personal, args.debounce, FI_GRID, POWER_GRID)

    hours = {s: sum(len(seg["freeze"]) for seg in test[s]) / SAMPLE_RATE_HZ / 3600 for s in subjects}
    rows = []
    for s in subjects + ["POOLED"]:
        row = {"subject": s}
        for m in METHODS:
            picked = [results[m][x] for x in (subjects if s == "POOLED" else [s])]
            tp, fn, fp, tn = sum(r["tol"] for r in picked)
            h = sum(hours.values()) if s == "POOLED" else hours[s]
            row[f"sens_{m[:4]}"] = rate(tp, tp + fn)
            row[f"spec_{m[:4]}"] = rate(tn, tn + fp)
            row[f"fa/h_{m[:4]}"] = sum(r["fa"] for r in picked) / h
            row[f"ep_{m[:4]}"] = f"{sum(r['detected'] for r in picked)}/{sum(r['episodes'] for r in picked)}"
        rows.append(row)

    pd.set_option("display.width", 250)
    table = pd.DataFrame(rows)
    ordered = ["subject"] + [f"{k}_{m[:4]}" for k in ("sens", "spec", "fa/h", "ep") for m in METHODS]
    print(f"calibration {args.cal_min:g} min, window {args.window:g} s, debounce {args.debounce}, "
          f"min spec {args.min_spec if args.min_spec is not None else 'off'}; sens/spec use the 2 s tolerance")
    print(table[ordered].to_string(index=False, float_format=lambda v: f"{v:.2f}", na_rep="-"))


if __name__ == "__main__":
    main()
