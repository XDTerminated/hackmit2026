#!/usr/bin/env python3
"""
Prepare FoG-STAR labeled IMU windows for dashboard replay.

FoG-STAR (Zenodo 10.5281/zenodo.17037669): 22 people with Parkinson's disease,
4 IMUs (ankleL / ankleR / back / wrist) at 60 Hz, tri-axial acc (g) + gyro (deg/s),
expert video annotations of FoG onset/offset and severity, activity + task labels.

This script:
  1. streams sensor_data.csv with the stdlib csv module (no pandas needed),
  2. finds annotated FoG episodes per (subject, session, task),
  3. cuts a window [onset - pre, offset + post] around selected episodes,
  4. computes ankle acc / gyro magnitude for the more active ankle,
  5. derives DETECTION / CUE markers (the dataset has no cueing; labelled as derived)
     and takes RECOVERY from the dataset's FoG-offset label,
  6. writes frontend/public/data/replay/<event_id>.json and index.json.

Usage:
  python data/prepare_fogstar_replay.py --csv /path/to/sensor_data.csv --list
  python data/prepare_fogstar_replay.py --csv /path/to/sensor_data.csv \
      --pick 3:1:3:0 --pick 7:1:7:1 --title 3:1:3:0="FoG-STAR straight walk"

Pick keys are subject:session:task:episode_index (0-based within that recording).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

TASKS = {
    1: "timed up-and-go",
    2: "standing",
    3: "straight walking",
    4: "walking through doorway",
    5: "walking carrying water",
    6: "walking + counting",
    7: "360° turning",
}
ACTIVITY = {1: "walking", 2: "sit", 3: "stand", 4: "sit-to-stand", 5: "stand-to-sit", 6: "turn-right", 7: "turn-left"}
SEVERITY = {1: "shuffling", 2: "trembling", 3: "akinesia"}
FS = 60.0

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "data" / "replay"


def mag(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


def load(csv_path: Path):
    """Group rows by recording. Returns {key: list_of_rows(dict)} preserving order."""
    recs: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    with csv_path.open(newline="") as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            key = (int(row["subjectID"]), int(row["sessionID"]), int(row["taskID"]))
            recs[key].append(row)
    return recs


def episodes(rows: list[dict]):
    """Yield (onset_idx, offset_idx_exclusive, severity) for fog==1 runs."""
    out = []
    start = None
    sev = 0
    for i, r in enumerate(rows):
        f = int(float(r["fog"]))
        if f == 1 and start is None:
            start = i
            sev = int(float(r["fog_severity"] or 0))
        elif f == 0 and start is not None:
            out.append((start, i, sev))
            start = None
    if start is not None:
        out.append((start, len(rows), sev))
    return out


def ankle_series(rows: list[dict], side: str):
    acc = [mag(float(r[f"{side}_acc_x"]), float(r[f"{side}_acc_y"]), float(r[f"{side}_acc_z"])) for r in rows]
    gyr = [mag(float(r[f"{side}_gyro_x"]), float(r[f"{side}_gyro_y"]), float(r[f"{side}_gyro_z"])) for r in rows]
    return acc, gyr


def estimate_cadence(acc: list[float]) -> float:
    """Steps/min from local maxima above mean + 0.7 sd with >=0.38 s spacing
    (mirrors frontend/lib/demoEngine.ts estimateCadence)."""
    if len(acc) < 30:
        return 0.0
    mu = statistics.fmean(acc)
    sd = statistics.pstdev(acc) or 1e-6
    thr = mu + 0.7 * sd
    min_gap = int(0.38 * FS)
    peaks = []
    last = -min_gap
    for i in range(1, len(acc) - 1):
        if acc[i] > thr and acc[i] >= acc[i - 1] and acc[i] >= acc[i + 1] and i - last >= min_gap:
            peaks.append(i)
            last = i
    if len(peaks) < 3:
        return 0.0
    return 60.0 * (len(peaks) - 1) / ((peaks[-1] - peaks[0]) / FS)


def build_event(key, rows, ep, ep_index, pre_s, post_s, title=None, event_id=None):
    subj, sess, task = key
    on, off, sev = ep
    a = max(0, on - int(pre_s * FS))
    b = min(len(rows), off + int(post_s * FS))
    win = rows[a:b]

    accL, gyrL = ankle_series(win, "ankleL")
    accR, gyrR = ankle_series(win, "ankleR")
    pre_n = on - a
    varL = statistics.pvariance(accL[:pre_n]) if pre_n > 5 else 0
    varR = statistics.pvariance(accR[:pre_n]) if pre_n > 5 else 0
    side = "ankleR" if varR >= varL else "ankleL"
    acc, gyr = (accR, gyrR) if side == "ankleR" else (accL, gyrL)

    onset_t = pre_n / FS
    offset_t = (off - a) / FS
    duration = len(win) / FS
    baseline = estimate_cadence(acc[:pre_n]) or 100.0

    samples = [
        {"t": round(i / FS, 4), "acc_mag": round(acc[i], 4), "gyro_mag": round(gyr[i], 2), "fog": int(float(win[i]["fog"]))}
        for i in range(len(win))
    ]
    # Derived markers: an on-device detector would flag ~0.4 s after labelled onset;
    # the cue follows detection by ~0.6 s. Recovery = dataset FoG offset (labelled).
    detection_t = round(onset_t + 0.4, 3)
    cue_t = round(detection_t + 0.6, 3)
    recovery_t = round(offset_t, 3)

    eid = event_id or f"fogstar-s{subj:02d}-t{task}-e{ep_index}"
    activities = sorted({ACTIVITY.get(int(float(r["activity"])), "?") for r in win[on - a : off - a]})
    return {
        "event_id": eid,
        "source": "FoG-STAR",
        "title": title or f"FoG-STAR {TASKS[task]} (S{subj:02d})",
        "subject_id": f"S{subj:02d}",
        "session_id": str(sess),
        "task": TASKS[task],
        "activities_during_fog": activities,
        "label": "freeze_like",
        "fog_severity": SEVERITY.get(sev),
        "sensor": f"{side} (acc + gyro magnitude)",
        "sample_rate_hz": FS,
        "baseline_cadence_bpm": round(baseline),
        "duration_s": round(duration, 3),
        "fog_onset_t": round(onset_t, 3),
        "fog_offset_t": round(offset_t, 3),
        "markers": {"detection_t": detection_t, "cue_t": cue_t, "recovery_t": recovery_t},
        "markers_source": {
            "detection": "derived: labelled FoG onset + 0.4 s detector latency",
            "cue": "derived: no cueing in dataset; detection + 0.6 s (demo)",
            "recovery": "dataset: expert-labelled FoG offset",
        },
        "citation": "Turetta et al., FoG-STAR, Zenodo 10.5281/zenodo.17037669",
        "samples": samples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--list", action="store_true", help="print candidate episodes")
    ap.add_argument("--pick", action="append", default=[], help="subject:session:task:episode_index")
    ap.add_argument("--title", action="append", default=[], help='key="Title" override')
    ap.add_argument("--id", action="append", default=[], help='key=event_id override')
    ap.add_argument("--pre", type=float, default=6.0)
    ap.add_argument("--post", type=float, default=4.0)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    recs = load(args.csv)

    if args.list:
        print("key(subj:sess:task:idx)  task                      sev        onset_s  dur_s  pre_walk_s  post_s")
        for key in sorted(recs):
            rows = recs[key]
            eps = episodes(rows)
            for i, (on, off, sev) in enumerate(eps):
                prev_off = eps[i - 1][1] if i else 0
                next_on = eps[i + 1][0] if i + 1 < len(eps) else len(rows)
                pre = (on - prev_off) / FS
                post = (next_on - off) / FS
                print(
                    f"{key[0]}:{key[1]}:{key[2]}:{i:<3} {TASKS[key[2]]:<25} {SEVERITY.get(sev, '?'):<10} "
                    f"{on / FS:7.1f} {(off - on) / FS:6.1f} {pre:10.1f} {post:7.1f}"
                )
        return

    titles = dict(t.split("=", 1) for t in args.title)
    ids = dict(t.split("=", 1) for t in args.id)
    args.out.mkdir(parents=True, exist_ok=True)
    index_events = []
    for pick in args.pick:
        s, se, t, i = (int(x) for x in pick.split(":"))
        key = (s, se, t)
        rows = recs[key]
        eps = episodes(rows)
        ev = build_event(key, rows, eps[i], i, args.pre, args.post, titles.get(pick, "").strip('"') or None, ids.get(pick))
        path = args.out / f"{ev['event_id']}.json"
        path.write_text(json.dumps(ev, separators=(",", ":")))
        index_events.append(
            {
                "event_id": ev["event_id"],
                "title": ev["title"],
                "file": path.name,
                "subject_id": ev["subject_id"],
                "task": ev["task"],
                "fog_severity": ev["fog_severity"],
                "duration_s": ev["duration_s"],
            }
        )
        print(f"wrote {path.name}: {ev['title']} · {ev['fog_severity']} · fog {ev['fog_onset_t']}–{ev['fog_offset_t']} s · baseline {ev['baseline_cadence_bpm']} BPM")

    index = {
        "dataset": {
            "name": "FoG-STAR",
            "participants": 22,
            "sample_rate_hz": 60,
            "sensors": "ankle IMU · accelerometer + gyroscope",
            "labels": "101 expert-labelled FoG episodes · severity · task",
            "citation": "Turetta et al., FoG-STAR: Freezing of Gait Severity, Tasks, Activities, and Ratings",
            "url": "https://doi.org/10.5281/zenodo.17037669",
        },
        "events": index_events,
    }
    (args.out / "index.json").write_text(json.dumps(index, indent=2))
    print(f"wrote index.json with {len(index_events)} events")


if __name__ == "__main__":
    main()
