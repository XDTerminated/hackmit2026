# Stride dashboard integration

The FastAPI session engine in `backend/` is the authoritative owner of monitoring state,
demo/replay/live source selection, event timelines, and WebSocket broadcasts.

- `frontend/` is the Next.js companion dashboard.
- `/` is the mobile User Mode; `/activity` and `/device` provide the companion views.
- `/research` is the technical dashboard for Demo, Replay, and Live demonstrations.
- The ESP32 can post normalized IMU packets to `POST /api/imu` or send them through `/ws/imu`.
- `backend/.env` is local-only and must never be committed. Use `.env.example` as the template.

The existing `analysis/`, `device/`, `app/`, `test_vectors/`, and dataset documentation remain the
team-owned hardware and research components. Cloud analysis never directly controls the actuator;
the local/edge loop remains responsible for cue dispatch.
