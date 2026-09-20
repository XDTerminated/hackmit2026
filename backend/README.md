# backend

Everything that is not the phone app. One Python environment (`pyproject.toml`, uv) serves `api/` and
`analysis/`; `arduino/` has its own tooling (Arduino App Lab).

```
cd backend
uv sync
```

| folder | what it is | start here |
|---|---|---|
| `arduino/` | what runs on the Arduino UNO Q: `fog_app/` (sketch + Linux-side glue + deploy script) and `bringup/` (wiring test) | `arduino/fog_app/README.md` |
| `api/` | the device's API server, the detector and the cadence tracker. Runs on the board (copied there by `arduino/fog_app/deploy.sh`) and on a laptop replaying a recording | below |
| `analysis/` | dataset cleaning, detector evaluation, experiments. Imports the detector from `api/`, never the other way round | `analysis/README.md` |

## api/

| file | what it does |
|---|---|
| `streaming_detector.py` | the one detector: a sample in, a decision every 0.5 s. NumPy only. Specified by `../test_vectors/README.md` |
| `cadence.py` | the wearer's walking cadence from the shin signal, for the auto-tempo cue. `--check` compares it with stride times from the gyro |
| `device_server.py` | the API in `../docs/api.md`: presets and settings, the cue, SQLite event log, REST + WebSocket, and the demo screen at `/demo` |
| `demo_page.html` | that demo screen: what the detector sees and decides, for a projector |
| `check_device_server.py` | pass/fail check of the server's cue-safety behaviour against a deterministic fake sensor |

```
uv run api/device_server.py                          # replay test_vectors/walk_then_freeze on port 8000
uv run api/device_server.py --csv ../data/own/raw/<file>.csv --seed-days 14
uv run api/check_device_server.py                    # 15 checks, about a minute
uv run analysis/verify_detector.py --check-vectors   # the detector still matches test_vectors/
```

On a laptop the server adds one route the board never has, `POST /api/v1/debug/freeze`, to force a cue for a demo.
