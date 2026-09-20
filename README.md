# Freezing-of-gait detector (HackMIT 2026)

A shin-worn prototype for people with Parkinson's disease. A motion sensor on the shin detects a
**freeze** (the feet stop while the legs tremble), and the wearer's phone plays a steady beat, at their
own walking pace, to help them step again. Events are logged so the wearer and their physio can see them.

**Not a medical device.** A hackathon prototype, never tested on patients; demos use healthy volunteers
acting a freeze.

## What is in here

```
frontend/            the phone app (Expo / React Native): Home, My data, Settings
backend/
  arduino/           what runs on the Arduino UNO Q: the sketch that reads the sensor at 64 Hz,
                     the App Lab app around it, and the deploy script
  api/               the device's API server and the detector it runs (Python; shipped to the board):
                     freeze detection, the cue, auto tempo, event log, REST + WebSocket, demo screen
  analysis/          the research behind the detector: dataset cleaning, evaluation, experiments
test_vectors/        recorded inputs and the detector's expected outputs: the detector's specification
docs/                api.md (the contract between api/ and frontend/), recording protocol, decisions,
                     screenshots, dataset licences
data/                datasets and our own recordings (not committed; see below)
CLAUDE.md            running project notes: every finding, number and decision so far
```

How the parts talk: `arduino/` streams sensor samples to `api/` on the board's Linux side; `api/` decides
when to cue and serves `docs/api.md` over Wi-Fi; `frontend/` plays the beat and shows the history.

## Run it

| to | do |
|---|---|
| set up Python | `cd backend && uv sync` |
| run the device API on a laptop (replays a recording, no board needed) | `cd backend && uv run api/device_server.py --seed-days 14` |
| run the phone app | `cd frontend && npm install && npm start`, scan the QR code with Expo Go |
| put everything on the board (USB) | `bash backend/arduino/fog_app/deploy.sh` |
| watch what the detector sees (for a projector) | open `http://<board or localhost>:8000/demo` |
| check nothing is broken | `cd backend && uv run api/check_device_server.py && uv run analysis/verify_detector.py --check-vectors`, and `cd frontend && npx tsc --noEmit` |

Phone and board must share a network that lets devices talk to each other: a phone or laptop hotspot works,
hotel and event Wi-Fi usually do not. Details: `backend/arduino/fog_app/README.md`.

## The detector, in one paragraph

On the acceleration magnitude (milli-g, 64 Hz), over a 4 s window every 0.5 s, weighted towards the most
recent samples: `freeze_index = power(3-8 Hz) / power(0.5-3 Hz)`. A window is positive when the index is
above 1.056, there is enough movement (band power above 178 mg²), and that power is not still collapsing
(which is someone simply stopping). A cue starts after two positive windows in a row if the wearer was walking
in the last 5 s, plays for at least 5 s, and continues while windows stay positive. The exact algorithm and
constants: `test_vectors/README.md`.

## Results so far

| tested on | freezes caught | false cues | time to cue (median) |
|---|---|---|---|
| Daphnet: 10 patients, leave-one-subject-out | 221 / 237 (93%) | 47 per hour | 1.2 s |
| Mendeley: 12 patients the detector never saw | 291 / 324 (90%) | 48 per hour | 1.5 s |
| Our own recordings: 2 healthy volunteers acting freezes, 8 min | 12 / 12 | 0 | 2.1 s (1.6 s on "catch more") |

Patient numbers come from lab protocols designed to provoke freezes; they are not predictions for daily life.
Auto tempo measures walking cadence to within 2.4 steps a minute of a gyroscope reference. What was tried and
rejected, and why, is in `CLAUDE.md`.

## Data

Nothing large is committed.

- **Daphnet** (86 MB): download from https://archive.ics.uci.edu/dataset/245/daphnet+freezing+of+gait, put the
  `S??R??.txt` files in `data/daphnet/raw/`, then `uv run analysis/clean_daphnet.py` in `backend/`.
- **Mendeley multimodal** (3.9 GB): `uv run analysis/download_mendeley.py`, then `uv run analysis/clean_mendeley.py`.
- **Own recordings** go in `data/own/raw/` (made from the board's page on port 7000; `docs/recording-protocol.md`).

Credits: Daphnet Freezing of Gait, Bächlin et al., IEEE TITB 14(2), 2010 (`docs/daphnet/README.txt`).
Multimodal Dataset of Freezing of Gait in Parkinson's Disease, Li et al., Mendeley Data v3,
doi:10.17632/r8gmbtv7w2.3, CC BY 4.0; Zhang et al., Scientific Data 9, 2022.
