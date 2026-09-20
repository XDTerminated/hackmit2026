"""RunPod IMU classifier — MOCK by default.

This service is SECONDARY VERIFICATION only. It must never command the
haptic motor. The local/edge detector owns cue dispatch.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from models import RunPodResult


def runpod_configured() -> bool:
    return bool(os.getenv("RUNPOD_API_KEY") and os.getenv("RUNPOD_ENDPOINT_ID"))


async def infer_gait(
    features: dict[str, Any],
    *,
    hint: Optional[str] = None,
) -> RunPodResult:
    """Classify a short IMU window.

    `hint` is used only by the mock path so the demo can produce a
    freeze-like verification without a trained endpoint.
    """
    if not runpod_configured():
        return _mock(hint=hint, features=features)

    endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID", "")
    api_key = os.getenv("RUNPOD_API_KEY", "")
    url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"input": features},
            )
            resp.raise_for_status()
            body = resp.json()
        output = body.get("output") or body
        classification = str(output.get("classification", "unknown"))
        if classification not in ("walking", "freeze_like", "unknown"):
            classification = "unknown"
        confidence = float(output.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        version = str(output.get("model_version", "runpod-unknown"))
        return RunPodResult(
            classification=classification,  # type: ignore[arg-type]
            confidence=confidence,
            model_version=version,
            status="complete",
            note="Secondary verification only. Does not drive the actuator.",
        )
    except Exception:
        # Graceful fallback — never crash the intervention loop.
        mock = _mock(hint=hint, features=features)
        mock.status = "error"
        mock.note = (
            "RunPod request failed; serving mock verification. "
            "Cloud outage cannot affect local cueing."
        )
        return mock


def _mock(*, hint: Optional[str], features: dict[str, Any]) -> RunPodResult:
    variance = float(features.get("accel_variance", 1.0))
    if hint == "freeze_like" or variance < 0.35:
        classification = "freeze_like"
        confidence = 0.91 if hint == "freeze_like" else 0.78
    elif hint == "walking" or variance > 0.8:
        classification = "walking"
        confidence = 0.18
    else:
        classification = "unknown"
        confidence = 0.42
    return RunPodResult(
        classification=classification,  # type: ignore[arg-type]
        confidence=confidence,
        model_version="mock-imu-v0",
        status="mock",
        note="Mock secondary verification. Does not drive the actuator.",
    )
