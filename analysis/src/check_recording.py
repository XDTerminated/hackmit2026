"""Check a recording from the board against everything the detector assumes.

Record a session from the diagnostics page of device/fog_app (port 7000), download the CSV and
run this on it. It answers, in order:

  1. Timing: is it really 64 Hz, and how many samples were lost?
  2. Scale:  does gravity read ~1000 mg, and is anything clipping?
  3. Signal: are "still" and "walking" as far apart in band power as in the patient data,
             so that the detector's two amplitude thresholds make sense for this sensor?
  4. Detector: what the frozen detector does on this recording.

Rows are t_us, ax_mg, ay_mg, az_mg, gx_dps, gy_dps, gz_dps; anything else (header, stray text) is
skipped. An optional 8th column is treated as a label (e.g. walking / standing / freezing) and the
detector results are then broken down by label.

Usage: python src/check_recording.py path/to/recording.csv
"""

import sys

import numpy as np
import pandas as pd

from streaming_detector import DetectorParams, StreamingDetector, run

PERIOD_US = 1_000_000 / 64
COLUMNS = ["t_us", "ax_mg", "ay_mg", "az_mg", "gx_dps", "gy_dps", "gz_dps"]
ACC_FULL_SCALE_MG = 8000


def parse(path):
    rows, labels, skipped = [], [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            parts = line.split(",")
            try:
                values = [float(v) for v in parts[:7]] if len(parts) >= 7 else None
            except ValueError:
                values = None
            if values is None:
                skipped += bool(line) and not line.startswith("t_us")
                continue
            rows.append(values)
            labels.append(parts[7].strip() if len(parts) > 7 else "")
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["label"] = labels
    return df, skipped


def verdict(ok, text):
    print(f"  [{'OK' if ok else '!!'}] {text}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    df, skipped = parse(sys.argv[1])
    if len(df) < 64 * 10:
        raise SystemExit(f"Only {len(df)} samples parsed; need at least 10 s of data")
    p = DetectorParams()

    print(f"{len(df)} samples parsed, {skipped} unreadable lines skipped")

    print("\n1. Timing")
    # micros() wraps every ~71 minutes; unwrap before differencing.
    t = np.unwrap(df["t_us"].to_numpy(), period=2**32)
    dt = np.diff(t)
    rate = 1e6 / np.median(dt)
    lost = int(np.round(dt[dt > 1.5 * PERIOD_US] / PERIOD_US - 1).sum())
    jitter_ok = np.mean(np.abs(dt - PERIOD_US) < 1000)
    print(f"  duration {(t[-1] - t[0]) / 1e6:.1f} s, median interval {np.median(dt):.0f} us = {rate:.2f} Hz")
    verdict(abs(rate - 64) < 0.2, f"sample rate is {rate:.2f} Hz (detector bands assume 64.00)")
    verdict(jitter_ok > 0.99, f"{100 * jitter_ok:.1f}% of intervals within 1 ms of {PERIOD_US:.0f} us")
    verdict(lost == 0, f"{lost} samples lost in {int((dt > 1.5 * PERIOD_US).sum())} gaps"
                       + ("" if lost == 0 else " -> the Bridge is not keeping up; send several samples per notify"))

    print("\n2. Scale")
    acc = df[["ax_mg", "ay_mg", "az_mg"]].to_numpy()
    mag = np.linalg.norm(acc, axis=1)
    gravity = np.median(mag)
    clipped = np.mean(np.abs(acc).max(axis=1) > 0.98 * ACC_FULL_SCALE_MG)
    verdict(900 < gravity < 1100, f"median |acc| = {gravity:.0f} mg (expect ~1000; patient datasets read 1030-1080)")
    verdict(clipped < 0.001, f"{100 * clipped:.2f}% of samples near the +-8 g limit; peak axis value {np.abs(acc).max():.0f} mg")
    gyro_peak = df[["gx_dps", "gy_dps", "gz_dps"]].abs().to_numpy().max()
    verdict(gyro_peak < 1950, f"peak gyro {gyro_peak:.0f} deg/s (limit 2000)")

    print("\n3. Signal levels")
    frames = run(StreamingDetector(p), axes=acc)
    frames["label"] = df["label"].to_numpy()[frames["sample_index"]]
    power = frames["total_power"]
    still, walking = power < p.power_threshold, frames["loco_power"] > p.walk_loco_power
    print(f"  total band power percentiles 10/50/90: {np.percentile(power, [10, 50, 90]).round(0)} mg^2")
    print(f"  frames still (< {p.power_threshold:g}): {100 * still.mean():.0f}%   "
          f"walking (loco > {p.walk_loco_power:g}): {100 * walking.mean():.0f}%   "
          f"in between: {100 * (~still & ~walking).mean():.0f}%")
    print("  Patient data: still is ~10-30 mg^2, walking is >10,000 mg^2. If a recording with both standing and")
    print("  walking does not split like that, the amplitude thresholds need shifting for this sensor or mounting.")

    print("\n4. Frozen detector on this recording")
    cue_starts = int((frames["cue_on"] & ~frames["cue_on"].shift(fill_value=False)).sum())
    print(f"  raw positive in {100 * frames['positive'].mean():.0f}% of frames, cue on {100 * frames['cue_on'].mean():.0f}%, "
          f"{cue_starts} cues started in {len(frames) * p.step / p.sample_rate_hz / 60:.1f} min")
    if frames["label"].ne("").any():
        table = frames.groupby("label").agg(frames=("positive", "size"), positive=("positive", "mean"),
                                            cue_on=("cue_on", "mean"), median_fi=("freeze_index", "median"),
                                            median_power=("total_power", "median"))
        print(table.round(2).to_string())
    if lost:
        print("  (results above are unreliable while samples are being lost)")


if __name__ == "__main__":
    main()
