"""Check the streaming detector (api/streaming_detector.py) and maintain the firmware test vectors.

  python analysis/verify_detector.py                   same as --verify
  python analysis/verify_detector.py --verify          it reproduces the batch code (baseline_fi +
                                                       simulate_device) on all of Daphnet; what float32 changes
  python analysis/verify_detector.py --check-vectors   it still reproduces test_vectors/
  python analysis/verify_detector.py --export          rewrite test_vectors/ (the firmware contract: only
                                                       after a deliberate change to the detector)
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from detector import DetectorParams, StreamingDetector, run

ROOT = Path(__file__).resolve().parents[2]  # repo root
CLEAN_DIR = ROOT / "data" / "daphnet" / "clean"
VECTOR_DIR = ROOT / "test_vectors"


def verify():
    from baseline_fi import STEP_S, window_features
    from simulate_device import CueConfig, cue_logic, stop_veto

    p = DetectorParams()
    cfg = CueConfig("reference", debounce=p.debounce_frames, gate_lookback_s=p.gate_lookback_frames * STEP_S,
                    gate_min_walk_s=p.gate_min_walk_frames * STEP_S, hold_s=p.hold_frames * STEP_S)
    exact, single = StreamingDetector(p), StreamingDetector(p, np.float32)

    n_frames = worst_fi = worst_power = 0
    cue_mismatch = axes_cue_diff = f32_positive_diff = f32_cue_diff = 0
    f32_worst = 0.0
    for path in sorted(CLEAN_DIR.glob("S*.csv")):
        for _, seg in pd.read_csv(path).groupby("segment"):
            mag = seg["acc_mag"].to_numpy()
            fi, power, _ = window_features(mag, p.window, p.step, p.ramp_power)
            cue = cue_logic(fi, power, p.fi_threshold, p.power_threshold, cfg, stop_veto(power, p.stop_veto_ratio))

            got = run(exact, magnitudes=mag)
            n_frames += len(got)
            worst_fi = max(worst_fi, np.max(np.abs(got.freeze_index - fi) / np.maximum(fi, 1e-12)))
            worst_power = max(worst_power, np.max(np.abs(got.total_power - power) / np.maximum(power, 1e-12)))
            cue_mismatch += int((got.cue_on.to_numpy() != cue).sum())

            # What the device will really do: magnitude from the three axes, in float32.
            from_axes = run(exact, axes=seg[["acc_f", "acc_v", "acc_l"]].to_numpy())
            axes_cue_diff += int((from_axes.cue_on != got.cue_on).sum())
            f32 = run(single, axes=seg[["acc_f", "acc_v", "acc_l"]].to_numpy().astype(np.float32))
            f32_positive_diff += int((f32.positive != from_axes.positive).sum())
            f32_cue_diff += int((f32.cue_on != from_axes.cue_on).sum())
            f32_worst = max(f32_worst, np.max(np.abs(f32.freeze_index - from_axes.freeze_index)
                                              / np.maximum(from_axes.freeze_index, 1e-12)))
        print(f"  {path.stem} checked", flush=True)

    print(f"\n{n_frames} frames compared with the batch code (baseline_fi + simulate_device):")
    print(f"  max relative error: freeze index {worst_fi:.1e}, total power {worst_power:.1e}")
    print(f"  cue on/off mismatches: {cue_mismatch}")
    print(f"magnitude computed from the 3 axes instead of the stored acc_mag column: {axes_cue_diff} cue frames differ")
    print(f"float32 instead of float64: max relative freeze-index error {f32_worst:.1e}, "
          f"{f32_positive_diff} raw decisions and {f32_cue_diff} cue frames differ")
    ok = cue_mismatch == 0 and worst_fi < 1e-6 and worst_power < 1e-6
    print("VERIFY " + ("PASSED" if ok else "FAILED"))
    return ok


# (name, what to look for, chunk length in seconds)
FLAG_COLUMNS = ("positive", "armed", "cue_on", "stopping")   # written as 0/1 and compared exactly

SCENARIOS = [
    ("walk_then_freeze", "cue starts after walking runs into a freeze", 60),
    ("standing_still", "power below threshold the whole time, cue never on", 60),
    ("gate_blocked", "detector positive but no recent walking, so the cue must stay off", 60),
    ("long_freeze", "cue must keep playing through a long freeze after the gate has lapsed", 90),
]


def find_chunks():
    """Locate one chunk of cleaned data for each scenario. Returns {name: (subject, segment, start, stop)}."""
    p = DetectorParams()
    detector = StreamingDetector(p)
    lengths = {name: seconds * p.sample_rate_hz for name, _, seconds in SCENARIOS}
    found = {}
    longest_freeze = 0
    for path in sorted(CLEAN_DIR.glob("S*.csv")):
        for seg_id, seg in pd.read_csv(path).groupby("segment"):
            frames = run(detector, magnitudes=seg["acc_mag"].to_numpy())
            freeze = seg["freeze"].to_numpy().astype(bool)
            n = len(seg)

            def chunk(name, centre):
                start = int(np.clip(centre - lengths[name] // 2, 0, max(n - lengths[name], 0)))
                return path.stem, seg_id, start, min(start + lengths[name], n)

            starts = frames.sample_index[frames.cue_on & ~frames.cue_on.shift(fill_value=False)]
            if "walk_then_freeze" not in found:
                for s in starts:
                    if freeze[s] and not freeze[max(s - 20 * p.sample_rate_hz, 0):s - 3 * p.sample_rate_hz].any():
                        found["walk_then_freeze"] = chunk("walk_then_freeze", s)
                        break
            if "standing_still" not in found:
                quiet = (frames.total_power < p.power_threshold).rolling(lengths["standing_still"] // p.step).sum()
                hit = frames.sample_index[quiet == lengths["standing_still"] // p.step]
                if len(hit):
                    found["standing_still"] = chunk("standing_still", hit.iloc[0] - lengths["standing_still"] // 2)
            if "gate_blocked" not in found:
                blocked = frames.positive & frames.positive.shift(fill_value=False) & ~frames.armed & ~frames.cue_on
                if blocked.sum() >= 4:
                    found["gate_blocked"] = chunk("gate_blocked", frames.sample_index[blocked].iloc[0])

            edges = np.flatnonzero(np.diff(np.concatenate([[0], freeze.astype(int), [0]])))
            for s, e in zip(edges[::2], edges[1::2]):
                cued = frames.cue_on[(frames.sample_index >= s) & (frames.sample_index < e)]
                if e - s > longest_freeze and e - s < 60 * p.sample_rate_hz and len(cued) and cued.mean() > 0.7:
                    longest_freeze = e - s
                    found["long_freeze"] = chunk("long_freeze", (s + e) // 2)
    return found


def export():
    p = DetectorParams()
    detector = StreamingDetector(p)
    VECTOR_DIR.mkdir(exist_ok=True)
    chunks = find_chunks()
    summary = []
    for name, description, _ in SCENARIOS:
        if name not in chunks:
            print(f"  no chunk found for {name}")
            continue
        subject, seg_id, start, stop = chunks[name]
        df = pd.read_csv(CLEAN_DIR / f"{subject}.csv")
        part = df[df.segment == seg_id].iloc[start:stop]
        axes = part[["acc_f", "acc_v", "acc_l"]].to_numpy()

        frames = run(detector, axes=axes)  # fresh state: exactly what the C code will see
        frames["label_freeze"] = part["freeze"].to_numpy()[frames.sample_index]
        for col in FLAG_COLUMNS:
            frames[col] = frames[col].astype(int)

        pd.DataFrame(axes, columns=["ax_mg", "ay_mg", "az_mg"]).to_csv(
            VECTOR_DIR / f"{name}_input.csv", index=False, float_format="%.1f")
        frames.to_csv(VECTOR_DIR / f"{name}_expected.csv", index=False, float_format="%.6g")
        summary.append(dict(vector=name, source=f"{subject} seg {seg_id} @{start / p.sample_rate_hz:.0f}s",
                            samples=len(axes), frames=len(frames), positive=frames.positive.sum(),
                            armed=frames.armed.sum(), cue_on=frames.cue_on.sum(),
                            labelled_freeze=frames.label_freeze.sum(), checks=description))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 90)
    print(pd.DataFrame(summary).to_string(index=False))
    print(f"\nWrote test vectors to {VECTOR_DIR}")


def check_vectors():
    """Replay every test vector and compare with its expected file, as the C port will have to."""
    ok = True
    for expected_path in sorted(VECTOR_DIR.glob("*_expected.csv")):
        expected = pd.read_csv(expected_path)
        axes = pd.read_csv(str(expected_path).replace("_expected", "_input")).to_numpy()
        got = run(StreamingDetector(), axes=axes)
        same = len(got) == len(expected) and all(
            (got[c].astype(int) == expected[c]).all() for c in FLAG_COLUMNS
        ) and np.allclose(got["freeze_index"], expected["freeze_index"], rtol=1e-4)
        print(f"  {expected_path.name}: {len(got)} frames {'match' if same else 'DIFFER'}")
        ok &= same
    print("CHECK " + ("PASSED" if ok else "FAILED: the detector no longer matches test_vectors/ (re-export if intended)"))
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--check-vectors", action="store_true")
    args = parser.parse_args()
    if args.check_vectors:
        raise SystemExit(0 if check_vectors() else 1)
    if not CLEAN_DIR.exists():
        raise SystemExit(f"No cleaned data in {CLEAN_DIR}; run clean_daphnet.py first")
    if args.verify or not args.export:
        if not verify():
            raise SystemExit(1)
    if args.export:
        export()


if __name__ == "__main__":
    main()
