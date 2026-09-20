"""Can the cue start sooner after an abrupt freeze, and what does it cost in false cues?

On our own recordings (v3 detector) the cue starts a median 2.1 s after the freeze label. Three
things hold it back: the debounce (2 frames = 0.5 s), the frame period (a frame lands every 0.5 s),
and above all the walking that still fills the 4 s window (the index needs 1-3 s to rise).

Candidates, all with the frozen thresholds, the walking gate, the 5 s hold and the stop rule:

  step      frames every 0.5 s (now) or every 0.25 s; the debounce is given in seconds
  fast path a second, more recency-weighted look at the same 4 s buffer (weights (i/255)^k). It
            may start a cue on its own when its freeze index passes a (higher) threshold. The slow
            path stays as it is, so nothing that is caught today is lost.

Scored on own recordings (latency, false cues) and on the patient datasets (episodes caught, false
cues per hour). Nothing here is nested: the choice is made looking at all the data.

Usage: python src/onset_experiment.py
"""

import numpy as np
import pandas as pd

from baseline_fi import SAMPLE_RATE_HZ, clean_dir, event_metrics, window_features
from evaluate_own import HOLD_TAIL_S, RAW_DIR, bouts

FI_TH, POWER_TH, STOP_RATIO, WALK_LOCO = 1.056, 178.0, 0.6, 10_000
WIN = 4 * SAMPLE_RATE_HZ
GATE_S, GATE_MIN_WALK_S, HOLD_S = 5, 1, 5


def features(magnitude, step, fast_power):
    fi, power, end_idx = window_features(magnitude, WIN, step, 1)
    lag = round(0.5 * SAMPLE_RATE_HZ / step)   # the stop rule compares with the window 0.5 s earlier
    def stopping(p):
        previous = np.concatenate([p[:lag], p[:-lag]])
        return p < STOP_RATIO * previous
    out = dict(end_idx=end_idx, slow=(fi > FI_TH) & (power > POWER_TH) & ~stopping(power),
               walking=power / (1 + fi) > WALK_LOCO)
    if fast_power:
        ffi, fpower, _ = window_features(magnitude, WIN, step, fast_power)
        out["fast_fi"], out["fast_ok"] = ffi, (fpower > POWER_TH) & ~stopping(fpower)
    return out


def cue_logic(f, step, debounce_s, fast_th=None, fast_debounce_s=0.0):
    frames = lambda seconds: max(1, round(seconds * SAMPLE_RATE_HZ / step))
    debounce, fast_debounce = frames(debounce_s), frames(fast_debounce_s)
    lookback, min_walk, hold = frames(GATE_S), frames(GATE_MIN_WALK_S), frames(HOLD_S)
    fast = f["fast_ok"] & (f["fast_fi"] > fast_th) if fast_th else np.zeros(len(f["slow"]), bool)

    cue = np.zeros(len(fast), bool)
    cue_on, run_slow, run_fast, hold_end, history = False, 0, 0, 0, []
    for i in range(len(cue)):
        run_slow = run_slow + 1 if f["slow"][i] else 0
        run_fast = run_fast + 1 if fast[i] else 0
        armed = sum(history) >= min_walk
        if cue_on:
            cue_on = f["slow"][i] or fast[i] or i < hold_end
        if not cue_on and armed and (run_slow >= debounce or run_fast >= fast_debounce > 0 and fast[i]):
            cue_on, hold_end = True, i + hold
        cue[i] = cue_on
        history.append(f["walking"][i])
        if len(history) > lookback:
            history.pop(0)
    return cue


def score_own(step, fast_power, **logic):
    latencies, false_cues, n = [], 0, 0
    for path in sorted(RAW_DIR.glob("*.csv")):
        data = pd.read_csv(path)
        labels = data["label"].fillna("").to_numpy()
        f = features(np.linalg.norm(data[["ax_mg", "ay_mg", "az_mg"]].to_numpy(), axis=1), step, fast_power)
        cue, index = cue_logic(f, step, **logic), f["end_idx"]
        freezes = [(a, b) for name, a, b in bouts(labels) if name == "freezing"]
        for a, b in freezes:
            n += 1
            hits = index[cue & (index >= a) & (index < b)]
            if len(hits):
                latencies.append((hits[0] - a) / SAMPLE_RATE_HZ)
        starts = index[cue & ~np.concatenate([[False], cue[:-1]])]
        false_cues += sum(labels[s] != "freezing" and not any(0 <= s - b < HOLD_TAIL_S * SAMPLE_RATE_HZ for _, b in freezes)
                          for s in starts)
    return {"own caught": f"{len(latencies)}/{n}", "own median s": round(float(np.median(latencies)), 2),
            "own worst s": round(max(latencies), 1), "own false": false_cues}


_patients = {}


def score_patients(dataset, step, fast_power, **logic):
    episodes = detected = false = 0
    hours, latencies = 0.0, []
    for path in sorted(clean_dir(dataset).glob("*.csv")):
        key = (path, step, fast_power)
        if key not in _patients:
            _patients[key] = [(seg["freeze"].to_numpy().astype(bool), features(seg["acc_mag"].to_numpy(), step, fast_power))
                              for _, seg in pd.read_csv(path).groupby("segment") if len(seg) >= WIN]
        segments = [dict(end_idx=f["end_idx"], freeze=freeze) for freeze, f in _patients[key]]
        cues = [cue_logic(f, step, **logic) for _, f in _patients[key]]
        n, d, _, lat, fa = event_metrics(segments, cues)
        episodes, detected, false, latencies = episodes + n, detected + d, false + fa, latencies + lat
        hours += sum(len(freeze) for freeze, _ in _patients[key]) / SAMPLE_RATE_HZ / 3600
    return {f"{dataset} caught": f"{100 * detected / episodes:.0f}%", f"{dataset} FA/h": round(false / hours),
            f"{dataset} lat s": round(float(np.median(latencies)), 1)}


def main():
    candidates = [("v3 balanced (now)", 32, 0, dict(debounce_s=1.0)),
                  ("v3 catch_more (now)", 32, 0, dict(debounce_s=0.5)),
                  ("step 0.25, debounce 0.5 s", 16, 0, dict(debounce_s=0.5)),
                  ("step 0.25, debounce 0.25 s", 16, 0, dict(debounce_s=0.25))]
    for k in (2, 3):
        for th in (1.056, 1.5, 2.0, 3.0):
            for fd in (0.25, 0.5):
                candidates.append((f"step 0.25 + fast ramp^{k} FI>{th} for {fd} s", 16, k,
                                   dict(debounce_s=1.0, fast_th=th, fast_debounce_s=fd)))
    rows = []
    for name, step, fast_power, logic in candidates:
        row = {"candidate": name, **score_own(step, fast_power, **logic)}
        for dataset in ("daphnet", "mendeley"):
            row.update(score_patients(dataset, step, fast_power, **logic))
        rows.append(row)
        print(".", end="", flush=True)
    pd.set_option("display.width", 250)
    print("\n" + pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
