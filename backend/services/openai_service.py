"""OpenAI post-event analysis.

This is an observational cloud layer. It never selects or dispatches a cue.
The local/edge loop remains the sole actuator path.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from models import EventRecord, OpenAIPostEvent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
_ENDPOINT = "https://api.openai.com/v1/responses"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "observation": {"type": "string"},
        "recovery_seconds": {"type": "number"},
        "cue_bpm": {"type": "integer"},
        "next_step": {"type": "string"},
        "safety_note": {"type": "string"},
    },
    "required": [
        "summary",
        "observation",
        "recovery_seconds",
        "cue_bpm",
        "next_step",
        "safety_note",
    ],
}


def configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _text_from_response(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                if isinstance(content.get("text"), str):
                    chunks.append(content["text"])
    return "".join(chunks)


async def analyze_event(event: EventRecord) -> OpenAIPostEvent:
    """Return a strictly structured, non-actuating event observation."""
    model = os.getenv("OPENAI_MODEL", _MODEL)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        # Uvicorn's default handler surfaces warnings; keep this line sanitized
        # so a successful real request is auditable without exposing secrets.
        logger.warning(
            "openai_post_event status=not_configured episode_id=%s model=%s",
            event.episode_id,
            model,
        )
        return OpenAIPostEvent(status="not_configured", model=model, episode_id=event.episode_id)

    payload = {
        "episode_id": event.episode_id,
        "edge_classification": event.edge.classification,
        "edge_confidence": event.edge.confidence,
        "cue_bpm": event.cue.bpm,
        "observed_recovery_ms": event.recovery.time_ms,
        "pre_cadence_bpm": event.pre_cadence,
        "post_cadence_bpm": event.post_cadence,
    }
    body = {
        "model": model,
        "store": False,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": (
                "Summarize one experimental gait interruption event. Use observational language "
                "such as possible interruption and observed recovery. Do not diagnose, give medical "
                "advice, or claim clinical benefit. Do not recommend actuator changes; next_step "
                "must only describe data collection."
            )}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload)}]},
        ],
        "text": {"format": {"type": "json_schema", "name": "post_event_observation", "strict": True, "schema": _SCHEMA}},
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
        response.raise_for_status()
        parsed = json.loads(_text_from_response(response.json()))
        result = OpenAIPostEvent.model_validate(
            {**parsed, "status": "online", "model": model, "episode_id": event.episode_id}
        )
        logger.warning(
            "openai_post_event status=success episode_id=%s model=%s http_status=%s",
            event.episode_id, model, response.status_code,
        )
        return result
    except Exception as exc:
        logger.warning(
            "openai_post_event status=error episode_id=%s model=%s error=%s http_status=%s",
            event.episode_id, model, type(exc).__name__,
            getattr(getattr(exc, "response", None), "status_code", "unknown"),
        )
        status = getattr(getattr(exc, "response", None), "status_code", None)
        error_name = f"http_{status}" if status else type(exc).__name__
        return OpenAIPostEvent(status="error", model=model, episode_id=event.episode_id, error=error_name)
