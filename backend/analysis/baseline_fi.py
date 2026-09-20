"""Freeze Index baseline on cleaned Daphnet data, evaluated leave-one-subject-out.

Run clean_daphnet.py (or clean_mendeley.py) first. Detector (Moore / Baechlin et al. 2010), computed on
the mean-removed acceleration magnitude over a sliding window:

    freeze_index = power(3-8 Hz) / power(0.5-3 Hz)
    total_power  = power(0.5-8 Hz)            [mg^2, i.e. band-limited variance]
    freeze       = freeze_index > FI_TH and total_power > POWER_TH

The power threshold suppresses detections while standing still. With
--debounce N the cue only fires after N consecutive positive windows, which
trades latency for fewer false alarms. Both thresholds are tuned on the training
subjects and applied to the held-out subject: by default for max balanced
accuracy, or with --min-spec X for max sensitivity at a specificity of at least
X. Each window is labelled by its last sample, which is what a real-time
detector sees.

Reported per held-out subject:
  sens/spec (strict)  every window counted as-is
  sens/spec (tol)     Baechlin-style 2 s tolerance: a missed window in the first
                      2 s of a freeze, or a detection in the 2 s after one ends,
                      is not counted as an error (this is what the paper reports)
  episodes            freeze episodes with at least one detection
  latency             median time from freeze onset to first detection, over
                      episodes where the detector was not already firing at onset
  pre_on              detected episodes where it was already firing at onset
                      (either gait already degrading before the annotated
                      onset, or a false alarm that ran into a freeze; the
                      labels cannot tell these apart)
  false_cues/h        detection bursts per hour that overlap no freeze
  cue_on_%            share of all windows in which the detector is on

Usage: python analysis/baseline_fi.py [--windows 2 3 4] [--debounce N] [--min-spec X] [--dataset daphnet|mendeley]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # repo root
DATASETS = ["daphnet", "mendeley"]


def clean_dir(dataset):
    return ROOT / "data" / dataset / "clean"



SAMPLE_RATE_HZ = 64
STEP_S = 0.5
LOCO_BAND_HZ = (0.5, 3.0)
FREEZE_BAND_HZ = (3.0, 8.0)
TOLERANCE_S = 2.0

FI_GRID = np.round(np.logspace(np.log10(0.3), np.log10(10), 40), 3)
POWER_GRID = np.concatenate([[0], np.round(np.logspace(1, 5, 33))])  # mg^2


def window_features(signal, win, step, ramp_power=0):
    """Freeze index and total band power for each sliding window of signal.

    ramp_power > 0 weights the window from 0 (oldest sample) to 1 (newest), raised to that
    power, so that old movement counts for less and the detector reacts sooner
    (see latency_experiment.py). 0 is the plain rectangular window.

    Returns (freeze_index, total_power, end_idx), end_idx being the index of
    the last sample of each window.
    """
    n = (len(signal) - win) // step + 1
    idx = np.arange(win)[None, :] + step * np.arange(n)[:, None]
    weights = np.linspace(0, 1, win) ** ramp_power if ramp_power else np.ones(win)
    frames = signal[idx]
    frames = (frames - np.average(frames, axis=1, weights=weights)[:, None]) * weights

    freqs = np.fft.rfftfreq(win, 1 / SAMPLE_RATE_HZ)
    # Scaled so that summing a band gives the signal variance in that band.
    power = 2 * np.abs(np.fft.rfft(frames, axis=1)) ** 2 / (win * (weights**2).sum())
    loco = power[:, (freqs >= LOCO_BAND_HZ[0]) & (freqs < LOCO_BAND_HZ[1])].sum(axis=1)
    freeze = power[:, (freqs >= FREEZE_BAND_HZ[0]) & (freqs <= FREEZE_BAND_HZ[1])].sum(axis=1)

    freeze_index = freeze / np.maximum(loco, 1e-9)
    return freeze_index, loco + freeze, idx[:, -1]


def detect(fi, power, fi_th, power_th, debounce):
    """Detector output per window. Thresholds may be scalars or broadcastable grids.

    With debounce > 1 a window is positive only if it and the previous
    debounce - 1 windows all exceed the thresholds.
    """
    return debounced((fi > fi_th) & (power > power_th), debounce)


def debounced(pred, n):
    """True only where pred and the n - 1 entries before it (along axis 0) are all True."""
    out = pred.copy()
    for lag in range(1, n):
        out[lag:] &= pred[:-lag]
        out[:lag] = False
    return out


def runs(mask):
    """(start, end) index pairs for each run of True in mask (end exclusive)."""
    edges = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def label_windows(freeze, end_idx):
    """Window labels (label of the last sample) and the two tolerance zones.

    Zones are in frames, as in the reference x_countTxFx.m.
    """
    tol_frames = int(round(TOLERANCE_S / STEP_S))
    y = freeze[end_idx]
    on_zone = np.zeros(len(y), bool)   # first frames of a freeze: a miss is excused
    off_zone = np.zeros(len(y), bool)  # frames just after a freeze: a detection is excused
    for start, end in runs(y):
        on_zone[start:min(start + tol_frames, end)] = True
        off_zone[end:end + tol_frames] = True
    off_zone &= ~y
    return dict(y=y, on_zone=on_zone, off_zone=off_zone)


def load_subject(path, win, step, ramp_power=0):
    """Window every segment of one subject. Returns a list of per-segment dicts."""
    df = pd.read_csv(path)
    segments = []
    for _, seg in df.groupby("segment"):
        freeze = seg["freeze"].to_numpy().astype(bool)
        fi, power, end_idx = window_features(seg["acc_mag"].to_numpy(), win, step, ramp_power)
        segments.append(dict(fi=fi, power=power, end_idx=end_idx, freeze=freeze,
                             **label_windows(freeze, end_idx)))
    return segments


def grid_counts(segments, debounce, fi_grid=FI_GRID, power_grid=POWER_GRID):
    """Positive-prediction counts for every (FI_TH, POWER_TH) pair.

    Windows are split into four groups (freeze/non-freeze x inside/outside a
    tolerance zone). Returns (pos, n): pos[g, i, j] is the number of detections
    in group g at grid cell (i, j), n[g] the group size.
    """
    pred = np.concatenate([
        detect(s["fi"][:, None, None], s["power"][:, None, None],
               fi_grid[None, :, None], power_grid[None, None, :], debounce)
        for s in segments])
    y = np.concatenate([s["y"] for s in segments])
    on_zone = np.concatenate([s["on_zone"] for s in segments])
    off_zone = np.concatenate([s["off_zone"] for s in segments])

    groups = [y & ~on_zone, y & on_zone, ~y & ~off_zone, ~y & off_zone]
    pos = np.stack([pred[g].sum(axis=0) for g in groups])
    n = np.array([g.sum() for g in groups])
    return pos, n


def confusion(pos, n, tolerant):
    """TP, FN, FP, TN (each an array over the grid) from grid_counts output."""
    neg = n[:, None, None] - pos
    if tolerant:
        tp = pos[0] + pos[1] + pos[3]
        fn = neg[0]
        fp = pos[2]
        tn = neg[2] + neg[3] + neg[1]
    else:
        tp, fn = pos[0] + pos[1], neg[0] + neg[1]
        fp, tn = pos[2] + pos[3], neg[2] + neg[3]
    return tp, fn, fp, tn


def counts(y, on_zone, off_zone, pred, tolerant):
    """TP, FN, FP, TN for one prediction vector; with tolerant=True using the Baechlin 2 s latency tolerance."""
    if tolerant:
        tp = (pred & (y | off_zone)).sum()
        fp = (pred & ~y & ~off_zone).sum()
        fn = (~pred & y & ~on_zone).sum()
        tn = (~pred & (~y | on_zone)).sum()
    else:
        tp, fn = (pred & y).sum(), (~pred & y).sum()
        fp, tn = (pred & ~y).sum(), (~pred & ~y).sum()
    return np.array([tp, fn, fp, tn])


def best_cell(pos, n, min_spec=None):
    """Grid cell with max balanced accuracy, or max sensitivity at spec >= min_spec."""
    tp, fn, fp, tn = confusion(pos, n, tolerant=True)
    with np.errstate(invalid="ignore"):
        sens, spec = tp / (tp + fn), tn / (tn + fp)
    if min_spec is None:
        score = sens + spec
    else:
        score = np.where(spec >= min_spec, sens, spec - 2)  # fall back to best spec
    return np.unravel_index(np.nanargmax(score), score.shape)


def rate(num, den):
    return num / den if den else float("nan")


def event_metrics(segments, preds):
    """Episode-level results for one subject; preds holds one boolean array per segment."""
    tol = int(TOLERANCE_S * SAMPLE_RATE_HZ)
    n_episodes = n_detected = n_pre_on = n_false_alarms = 0
    latencies = []
    for s, pred in zip(segments, preds):
        end_idx, freeze = s["end_idx"], s["freeze"]
        det_idx = end_idx[pred]

        near_freeze = freeze.copy()
        for start, end in runs(freeze):
            n_episodes += 1
            near_freeze[end:end + tol] = True
            hits = det_idx[(det_idx >= start) & (det_idx < end + tol)]
            if len(hits):
                n_detected += 1
                before = np.searchsorted(end_idx, start) - 1  # last window ending before onset
                if before >= 0 and pred[before]:
                    n_pre_on += 1
                else:
                    latencies.append((hits[0] - start) / SAMPLE_RATE_HZ)

        for start, end in runs(pred):
            if not near_freeze[end_idx[start:end]].any():
                n_false_alarms += 1
    return n_episodes, n_detected, n_pre_on, latencies, n_false_alarms


def loso_cell(grid, held_out, min_spec=None):
    """Best threshold cell using every subject in grid except held_out (None: use them all).

    grid maps subject -> grid_counts() output.
    """
    pos = sum(p for subject, (p, _) in grid.items() if subject != held_out)
    n = sum(c for subject, (_, c) in grid.items() if subject != held_out)
    return best_cell(pos, n, min_spec)


def score_subject(segments, preds):
    """Every count the reports need for one subject; preds holds one boolean array per segment."""
    pred = np.concatenate(preds)
    y, on_zone, off_zone = (np.concatenate([s[k] for s in segments]) for k in ("y", "on_zone", "off_zone"))
    n_episodes, n_detected, n_pre_on, latencies, n_false = event_metrics(segments, preds)
    return dict(strict=counts(y, on_zone, off_zone, pred, tolerant=False),
                tol=counts(y, on_zone, off_zone, pred, tolerant=True),
                episodes=n_episodes, detected=n_detected, pre_on=n_pre_on, latencies=latencies, fa=n_false,
                cue_frames=int(pred.sum()), frames=len(pred),
                hours=sum(len(s["freeze"]) for s in segments) / SAMPLE_RATE_HZ / 3600)


def summary_row(results, **labels):
    """One report row pooling a list of score_subject() results; labels become the leading columns."""
    strict, tol = sum(r["strict"] for r in results), sum(r["tol"] for r in results)
    latencies = [x for r in results for x in r["latencies"]]
    return {
        **labels,
        "sens": rate(strict[0], strict[0] + strict[1]), "spec": rate(strict[3], strict[2] + strict[3]),
        "sens_tol": rate(tol[0], tol[0] + tol[1]), "spec_tol": rate(tol[3], tol[2] + tol[3]),
        "episodes": f"{sum(r['detected'] for r in results)}/{sum(r['episodes'] for r in results)}",
        "pre_on": sum(r["pre_on"] for r in results),
        "latency_s": np.median(latencies) if latencies else float("nan"),
        "false_cues/h": sum(r["fa"] for r in results) / sum(r["hours"] for r in results),
        "cue_on_%": 100 * sum(r["cue_frames"] for r in results) / sum(r["frames"] for r in results),
    }


def evaluate(win_s, debounce, min_spec, dataset="daphnet"):
    win, step = int(win_s * SAMPLE_RATE_HZ), int(STEP_S * SAMPLE_RATE_HZ)
    files = sorted(clean_dir(dataset).glob("*.csv"))
    if not files:
        raise SystemExit(f"No cleaned data in {clean_dir(dataset)}; run clean_{dataset}.py first")

    data = {f.stem: load_subject(f, win, step) for f in files}
    grid = {subject: grid_counts(segments, debounce) for subject, segments in data.items()}

    rows, results = [], []
    for held_out, segments in data.items():
        i, j = loso_cell(grid, held_out, min_spec)
        fi_th, power_th = FI_GRID[i], POWER_GRID[j]
        result = score_subject(segments, [detect(s["fi"], s["power"], fi_th, power_th, debounce) for s in segments])
        results.append(result)
        rows.append(summary_row([result], subject=held_out, fi_th=fi_th, power_th=power_th))
    rows.append(summary_row(results, subject="POOLED", fi_th=float("nan"), power_th=float("nan")))

    i, j = loso_cell(grid, None, min_spec)
    return pd.DataFrame(rows), (FI_GRID[i], POWER_GRID[j])


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--windows", type=float, nargs="+", default=[2, 3, 4], help="window lengths in seconds")
    parser.add_argument("--debounce", type=int, default=1, help="consecutive positive windows needed to fire")
    parser.add_argument("--min-spec", type=float, default=None,
                        help="tune for max sensitivity at this specificity or better (default: balanced accuracy)")
    parser.add_argument("--dataset", choices=DATASETS, default="daphnet")
    args = parser.parse_args()

    pd.set_option("display.width", 200)
    summary = []
    for win_s in args.windows:
        table, deploy = evaluate(win_s, args.debounce, args.min_spec, args.dataset)
        print(f"\n=== window {win_s:g} s, step {STEP_S:g} s, debounce {args.debounce}, "
              f"min spec {args.min_spec if args.min_spec is not None else 'off'} ===")
        print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}", na_rep="-"))
        print(f"Thresholds tuned on all subjects (for the device): "
              f"freeze_index > {deploy[0]:g}, total_power > {deploy[1]:g} mg^2")
        summary.append(table.iloc[-1].drop(["subject", "fi_th", "power_th"]).rename(f"{win_s:g} s"))

    if len(summary) > 1:
        print("\n=== pooled results by window length ===")
        print(pd.DataFrame(summary).to_string(float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
