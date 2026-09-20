"""Random forest freeze detector on cleaned Daphnet data, leave-one-subject-out.

Same windows, labels and metrics as baseline_fi.py, so the two are directly
comparable. All features come from the acceleration magnitude, so they do not
depend on how the sensor is oriented on the leg. Each window also sees the freeze
index and power of the windows 2 s and 4 s earlier ("was the user walking just
before?"), which is causal and cheap to keep on a device.

The probability threshold for each fold is picked on out-of-subject predictions
from an inner grouped cross-validation over the training subjects, then the
forest is refit on all of them and applied to the held-out subject.

Usage: python analysis/train_rf.py [--window 4] [--debounce N] [--min-spec X] [--per-axis] [--save model.joblib]
"""

import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupKFold

from baseline_fi import (SAMPLE_RATE_HZ, STEP_S, clean_dir, counts, debounced, label_windows, score_subject,
                         summary_row)

BANDS_HZ = [(0.5, 1.5), (1.5, 3), (3, 5), (5, 8), (8, 12), (12, 20)]
LAGS_FRAMES = [4, 8]  # 2 s and 4 s earlier
TRAIN_STRIDE = 2      # train on every 2nd window; neighbours overlap by 87% and add little
PROB_GRID = np.linspace(0.02, 0.98, 97)
EPS = 1e-6
AXES = ["acc_f", "acc_v", "acc_l"]  # forward, vertical, lateral: only meaningful if mounted like Daphnet
AXIS_FEATURES = ["log_fi", "log_total", "log_std", "centroid"]


def segment_features(signal, win, step):
    """Feature table for every sliding window of one segment. Returns (DataFrame, end_idx)."""
    n = (len(signal) - win) // step + 1
    idx = np.arange(win)[None, :] + step * np.arange(n)[:, None]
    raw = signal[idx]
    frames = raw - raw.mean(axis=1, keepdims=True)

    freqs = np.fft.rfftfreq(win, 1 / SAMPLE_RATE_HZ)
    power = 2 * np.abs(np.fft.rfft(frames, axis=1)) ** 2 / win**2  # band sums are variances, mg^2

    def band(lo, hi):
        return power[:, (freqs >= lo) & (freqs < hi)].sum(axis=1)

    f = {}
    for lo, hi in BANDS_HZ:
        f[f"log_p_{lo:g}_{hi:g}"] = np.log(band(lo, hi) + EPS)
    loco, freeze = band(0.5, 3), band(3, 8)
    f["log_fi"] = np.log((freeze + EPS) / (loco + EPS))
    f["log_total"] = np.log(loco + freeze + EPS)

    gait = (freqs >= 0.5) & (freqs < 20)
    p = power[:, gait] / (power[:, gait].sum(axis=1, keepdims=True) + EPS)
    f["dom_freq"] = freqs[gait][np.argmax(p, axis=1)]
    f["dom_frac"] = p.max(axis=1)
    f["centroid"] = (p * freqs[gait]).sum(axis=1)
    f["entropy"] = -(p * np.log(p + EPS)).sum(axis=1)

    f["log_std"] = np.log(frames.std(axis=1) + EPS)
    f["log_range"] = np.log(np.ptp(frames, axis=1) + EPS)
    f["log_jerk"] = np.log(np.abs(np.diff(frames, axis=1)).mean(axis=1) + EPS)
    z = frames / (frames.std(axis=1, keepdims=True) + EPS)  # flat windows give 0, not NaN
    f["skew"] = (z**3).mean(axis=1)
    f["kurtosis"] = (z**4).mean(axis=1) - 3
    f["mean_cross"] = (np.diff(np.sign(frames), axis=1) != 0).mean(axis=1)

    for lag in LAGS_FRAMES:
        for name in ("log_fi", "log_total"):
            lagged = np.concatenate([np.full(min(lag, n), f[name][0]), f[name][:-lag]])[:n]
            f[f"{name}_lag{lag * STEP_S:g}s"] = lagged
    return pd.DataFrame(f), idx[:, -1]


def load_subject(path, win, step, per_axis):
    df = pd.read_csv(path)
    segments = []
    for _, seg in df.groupby("segment"):
        freeze = seg["freeze"].to_numpy().astype(bool)
        X, end_idx = segment_features(seg["acc_mag"].to_numpy(), win, step)
        if per_axis:
            for axis in AXES:
                extra, _ = segment_features(seg[axis].to_numpy(), win, step)
                X = X.join(extra[AXIS_FEATURES].add_prefix(f"{axis}_"))
        segments.append(dict(X=X, end_idx=end_idx, freeze=freeze, **label_windows(freeze, end_idx)))
    return segments


def stack(segments, key, stride=1):
    parts = [s[key][::stride] for s in segments]
    return pd.concat(parts, ignore_index=True) if key == "X" else np.concatenate(parts)


def make_forest():
    return RandomForestClassifier(n_estimators=150, min_samples_leaf=10, max_features="sqrt",
                                  class_weight="balanced_subsample", n_jobs=-1, random_state=0)


def pick_threshold(y, on_zone, off_zone, prob, min_spec):
    best, best_score = 0.5, -np.inf
    for th in PROB_GRID:
        tp, fn, fp, tn = counts(y, on_zone, off_zone, prob > th, tolerant=True)
        sens, spec = tp / (tp + fn), tn / (tn + fp)
        score = sens + spec if min_spec is None else (sens if spec >= min_spec else spec - 2)
        if score > best_score:
            best, best_score = th, score
    return best


def fit_fold(data, train_subjects, min_spec):
    """Fit on train_subjects; returns (forest, probability threshold)."""
    X = stack([s for subj in train_subjects for s in data[subj]], "X", TRAIN_STRIDE)
    labels = {k: np.concatenate([stack(data[subj], k, TRAIN_STRIDE) for subj in train_subjects])
              for k in ("y", "on_zone", "off_zone")}
    groups = np.concatenate([np.full(len(stack(data[subj], "y", TRAIN_STRIDE)), i)
                             for i, subj in enumerate(train_subjects)])

    prob = np.zeros(len(X))
    for fit_idx, val_idx in GroupKFold(n_splits=3).split(X, labels["y"], groups):
        prob[val_idx] = make_forest().fit(X.iloc[fit_idx], labels["y"][fit_idx]).predict_proba(X.iloc[val_idx])[:, 1]
    threshold = pick_threshold(labels["y"], labels["on_zone"], labels["off_zone"], prob, min_spec)
    return make_forest().fit(X, labels["y"]), threshold


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--window", type=float, default=4, help="window length in seconds")
    parser.add_argument("--debounce", type=int, default=1, help="consecutive positive windows needed to fire")
    parser.add_argument("--min-spec", type=float, default=None,
                        help="tune for max sensitivity at this specificity or better (default: balanced accuracy)")
    parser.add_argument("--per-axis", action="store_true",
                        help="add per-axis features (requires the sensor axes to be aligned as in Daphnet)")
    parser.add_argument("--save", help="also fit on all subjects and save the model with joblib")
    args = parser.parse_args()

    win, step = int(args.window * SAMPLE_RATE_HZ), int(STEP_S * SAMPLE_RATE_HZ)
    files = sorted(clean_dir("daphnet").glob("*.csv"))
    if not files:
        raise SystemExit("No cleaned Daphnet data; run clean_daphnet.py first")
    data = {f.stem: load_subject(f, win, step, args.per_axis) for f in files}
    subjects = list(data)

    rows, results, importances = [], [], []
    for held_out, segments in data.items():
        forest, threshold = fit_fold(data, [s for s in subjects if s != held_out], args.min_spec)
        importances.append(forest.feature_importances_)
        preds = [debounced(forest.predict_proba(s["X"])[:, 1] > threshold, args.debounce) for s in segments]
        result = score_subject(segments, preds)
        results.append(result)
        rows.append(summary_row([result], subject=held_out, prob_th=threshold))
        print(f"  fold {held_out} done", flush=True)
    rows.append(summary_row(results, subject="POOLED", prob_th=float("nan")))

    pd.set_option("display.width", 200)
    print(f"\n=== random forest, window {args.window:g} s, step {STEP_S:g} s, debounce {args.debounce}, "
          f"min spec {args.min_spec if args.min_spec is not None else 'off'} ===")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.2f}", na_rep="-"))

    names = data[subjects[0]][0]["X"].columns
    top = pd.Series(np.mean(importances, axis=0), index=names).sort_values(ascending=False)
    print("\nTop features (mean importance over folds):")
    print(top.head(10).to_string(float_format=lambda v: f"{v:.3f}"))

    if args.save:
        import joblib
        forest, threshold = fit_fold(data, subjects, args.min_spec)
        joblib.dump(dict(model=forest, threshold=threshold, features=list(names), window_s=args.window,
                         step_s=STEP_S, debounce=args.debounce), args.save)
        print(f"\nSaved model fitted on all subjects to {args.save} (probability threshold {threshold:.2f})")


if __name__ == "__main__":
    main()
