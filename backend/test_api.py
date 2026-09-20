"""Smoke tests for the FoG cueing research API (in-memory, mock services)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import time

from main import app


def test_health() -> None:
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "not a medical device" in body["disclaimer"].lower()


def test_session_seeded() -> None:
    with TestClient(app) as client:
        r = client.get("/api/session/current")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == "hackmit-demo-001"
        ids = [e["episode_id"] for e in body["events"]]
        assert ids[:3] == ["E1", "E2", "E3"]
        assert body["allowed_next_cues"][0]["bpm"] in (80, 95, 102)


def test_events_and_demo_reset() -> None:
    with TestClient(app) as client:
        r = client.get("/api/events")
        assert r.status_code == 200
        assert len(r.json()) >= 3
        reset = client.post("/api/demo/reset")
        assert reset.status_code == 200
        assert reset.json()["phase"] == "WALKING"


def test_imu_ingest() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/api/imu",
            json={
                "timestamp": 843920,
                "ax": 0.13,
                "ay": -0.42,
                "az": 9.71,
                "gx": 0.4,
                "gy": 2.7,
                "gz": -1.1,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "accel_mag" in body


def test_runpod_and_grok_mock() -> None:
    with TestClient(app) as client:
        rp = client.post("/api/runpod/inference", json={"hint": "freeze_like"})
        assert rp.status_code == 200
        assert rp.json()["classification"] == "freeze_like"
        assert rp.json()["status"] in ("mock", "complete", "error")
        grok = client.post("/api/grok/analyze")
        assert grok.status_code == 200
        body = grok.json()
        assert "next_experiment" in body
        assert "Insufficient" in body["confidence_statement"] or "No ranking" in body["confidence_statement"]
        rec = body.get("recommended_cue")
        if rec:
            assert rec["bpm"] in (80, 95, 102)


def test_cue_must_be_allowed() -> None:
    with TestClient(app) as client:
        bad = client.post("/api/cue", json={"pattern": "rhythmic", "bpm": 199})
        assert bad.status_code >= 400


def test_demo_freeze_then_recovery() -> None:
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        started = client.post("/api/demo/simulate-freeze")
        assert started.status_code == 200
        rec = client.post("/api/demo/simulate-recovery")
        assert rec.status_code == 200
        session = rec.json()
        assert any(e["episode_id"].startswith("E") for e in session["events"])
        assert session["analysis"] is not None
        assert "motor" in session["analysis"]["safety"].lower()


def test_two_clients_observe_same_automatic_sequence_and_reset() -> None:
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        with client.websocket_connect("/ws/imu") as phone, client.websocket_connect("/ws/imu") as research:
            # Each connection receives the same initial snapshot.
            for ws in (phone, research):
                snapshot = [ws.receive_json() for _ in range(7)]
                assert next(p["data"]["monitoring"] for p in snapshot if p["type"] == "session") is False
            client.post("/api/demo/start-walking")
            client.post("/api/demo/simulate-freeze")
            expected = ["POSSIBLE_FREEZE", "DETECTED", "CUE_TRIGGERED", "RECOVERY_MONITORING", "RECOVERED", "ANALYZING", "WALKING"]
            for ws in (phone, research):
                seen: list[str] = []
                deadline = time.monotonic() + 10
                while len(seen) < len(expected) and time.monotonic() < deadline:
                    message = ws.receive_json()
                    if message["type"] == "state":
                        phase = message["data"]["phase"]
                        if not seen and phase != "POSSIBLE_FREEZE":
                            continue
                        if phase in expected and (not seen or phase != seen[-1]):
                            seen.append(phase)
                assert seen[-len(expected):] == expected
            session = client.get("/api/session/current").json()
            assert session["events"][-1]["recovery"]["detected"] is True
            reset = client.post("/api/demo/reset").json()
            assert reset["monitoring"] is False
            assert reset["cue"]["active"] is False


def test_reset_cancels_active_demo_and_live_source_accepts_imu() -> None:
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        client.post("/api/demo/start-walking")
        client.post("/api/demo/simulate-freeze")
        time.sleep(0.2)
        client.post("/api/demo/reset")
        time.sleep(1.5)
        session = client.get("/api/session/current").json()
        assert session["monitoring"] is False
        assert session["cue"]["active"] is False
        assert session["phase"] == "WALKING"
        assert len(session["events"]) == 3
        assert client.post("/api/source", json={"source": "LIVE"}).json()["source"] == "LIVE"
        assert client.post("/api/monitoring/start").json()["source"] == "LIVE"
        sample = client.post("/api/imu", json={"timestamp": 100, "ax": 0, "ay": 0, "az": 9.81, "gx": 1, "gy": 0, "gz": 0})
        assert sample.status_code == 200
        assert sample.json()["accel_mag"] == 9.81
