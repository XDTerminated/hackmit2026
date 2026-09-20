# Freezing-of-gait detector (HackMIT 2026)

A shin-worn prototype that detects freezing of gait in Parkinson's disease from an IMU, plays a
metronome cue on the wearer's phone, at their own walking pace, to help them restart walking, and logs
events for a companion app.

**Not a medical device.** Prototype for a demo; never tested on patients.

## Repository layout

```
analysis/       Python: dataset cleaning, detector evaluation, firmware reference   (working)
device/         Arduino UNO Q: the App Lab app that runs on the board (sketch + Python) (working)
app/            companion phone app, Expo / React Native                              (working)
test_vectors/   the contract between analysis/ and device/: input and expected-output CSVs
docs/           dataset documentation and licences; API contract between device/ and app/
data/           datasets; only small files are committed, see below
CLAUDE.md       project notes, findings and decisions so far
```

Each part has its own README and its own tooling (uv, Arduino App Lab, npm). There is no shared
build system on purpose: the three parts share no code, only the two contracts above.

## The detector in one paragraph

On the acceleration magnitude (milli-g, 64 Hz), over a 4 s window every 0.5 s, mean-removed and weighted
towards the most recent samples so that it reacts quickly:
`freeze_index = power(3-8 Hz) / power(0.5-3 Hz)`; a window is positive when `freeze_index > 1.056`,
`power(0.5-8 Hz) > 178 mg^2`, and that power is not still collapsing (below 0.6 x the previous window's,
which is the wearer stopping rather than freezing). A cue starts after 2 consecutive positive windows if the wearer
was walking in the last 5 s, plays for at least 5 s, and continues while windows stay positive.
The exact algorithm and constants are in `test_vectors/README.md`.

## Getting the data

Raw datasets are not committed.

- **Daphnet** (86 MB): download from https://archive.ics.uci.edu/dataset/245/daphnet+freezing+of+gait
  and put the `S??R??.txt` files in `data/daphnet/raw/`. Then `uv run src/clean_daphnet.py` in `analysis/`.
- **Mendeley multimodal** (3.9 GB): `uv run src/download_mendeley.py`, then `uv run src/clean_mendeley.py`.

## Data credits

- Daphnet Freezing of Gait: Bächlin et al., IEEE TITB 14(2), 2010. See `docs/daphnet/README.txt`.
- Multimodal Dataset of Freezing of Gait in Parkinson's Disease: Li et al., Mendeley Data v3,
  doi:10.17632/r8gmbtv7w2.3, CC BY 4.0; Zhang et al., Scientific Data 9, 2022.
