"""Shared Pydantic models for the FoG cueing research prototype.

Language note: this is a research / assistive-technology prototype,
NOT a validated medical device. Classifications describe freeze-like
gait patterns, never a confirmed clinical freezing-of-gait diagnosis.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Phase(str, Enum):
    WALKING = "WALKING"
    POSSIBLE_FREEZE = "POSSIBLE_FREEZE"
    DETECTED = "DETECTED"
    CUE_TRIGGERED = "CUE_TRIGGERED"
    RECOVERY_MONITORING = "RECOVERY_MONITORING"
    RECOVERED = "RECOVERED"
    ANALYZING = "ANALYZING"


PHASE_LABELS: dict[Phase, str] = {
    Phase.WALKING: "WALKING",
    Phase.POSSIBLE_FREEZE: "POSSIBLE FREEZE",
    Phase.DETECTED: "DETECTED",
    Phase.CUE_TRIGGERED: "CUEING",
    Phase.RECOVERY_MONITORING: "RECOVERING",
    Phase.RECOVERED: "RECOVERED",
    Phase.ANALYZING: "ANALYZING",
}


class IMUPacket(BaseModel):
    timestamp: float = Field(..., description="Device or sim timestamp (ms)")
    ax: float
    ay: float
    az: float
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0
    # Optional when the edge firmware already computes cadence. If omitted,
    # LIVE mode stays honest and the UI shows that cadence is unavailable.
    cadence_bpm: Optional[float] = Field(default=None, ge=0.0, le=240.0)


class IMUSample(IMUPacket):
    accel_mag: float
    gyro_mag: float
    cadence_bpm: Optional[float] = None


class Classification(BaseModel):
    classification: Literal["walking", "freeze_like", "unknown"] = "unknown"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    source: str = "edge"
    latency_ms: Optional[int] = None
    model_version: Optional[str] = None
    note: str = "Research signal only — not a medical confirmation."


class CueParams(BaseModel):
    pattern: Literal["rhythmic", "pulse", "off"] = "rhythmic"
    bpm: int = Field(95, ge=40, le=180)
    active: bool = False


class RecoveryInfo(BaseModel):
    detected: bool = False
    time_ms: Optional[int] = None
    elapsed_ms: int = 0
    pre_cadence: Optional[float] = None
    post_cadence: Optional[float] = None
    event_duration_ms: Optional[int] = None


class EdgeResult(BaseModel):
    classification: Literal["walking", "freeze_like", "unknown"] = "walking"
    confidence: float = 0.08


class RunPodResult(BaseModel):
    classification: Literal["walking", "freeze_like", "unknown"] = "unknown"
    confidence: float = 0.0
    model_version: str = "mock-imu-v0"
    status: Literal["idle", "pending", "complete", "mock", "error"] = "idle"
    note: str = "Secondary verification only. Does not drive the actuator."


class CueInfo(BaseModel):
    pattern: str = "rhythmic"
    bpm: int = 95
    active: bool = False
    source: str = "edge_local"
    note: str = "Dispatched by the local/edge loop. Cloud models do not command the motor."


class RecoveryRecord(BaseModel):
    detected: bool = False
    time_ms: Optional[int] = None


class EventRecord(BaseModel):
    episode_id: str
    timestamp_iso: str
    edge: EdgeResult
    runpod: RunPodResult
    cue: CueInfo
    recovery: RecoveryRecord
    status: str = "Recovered"
    event_duration_ms: Optional[int] = None
    pre_cadence: Optional[float] = None
    post_cadence: Optional[float] = None


class GrokAnalysis(BaseModel):
    summary: str
    observation: str
    evidence: str
    next_experiment: str
    confidence_statement: str
    full_analysis: str
    session_summary: str = ""
    cue_comparison: str = ""
    observations: str = ""
    safety: str = (
        "Cloud analysis is observational. Grok and RunPod must never command "
        "the vibration motor. Cue timing stays on-device / edge-local."
    )
    limitation: str = (
        "Prototype with simulated or limited IMU. Not a diagnostic tool. "
        "Findings describe freeze-like gait patterns, not confirmed FoG."
    )
    recommended_cue: Optional[CueParams] = None
    mock: bool = True


class OpenAIPostEvent(BaseModel):
    """Constrained post-event summary; never controls the actuator."""

    status: Literal["online", "not_configured", "error"] = "not_configured"
    model: str = ""
    episode_id: str = ""
    summary: str = ""
    observation: str = ""
    recovery_seconds: float = 0.0
    cue_bpm: int = 95
    next_step: str = "Continue collecting observations."
    safety_note: str = (
        "Research observation only; this is not a diagnosis or medical advice."
    )
    error: Optional[str] = None


class SessionState(BaseModel):
    session_id: str = "hackmit-demo-001"
    monitoring: bool = False
    source: Literal["DEMO", "REPLAY", "LIVE"] = "DEMO"
    baseline_cadence_bpm: float = 102.0
    current_cadence_bpm: float = 102.0
    allowed_next_cues: list[CueParams] = Field(
        default_factory=lambda: [
            CueParams(pattern="rhythmic", bpm=80, active=False),
            CueParams(pattern="rhythmic", bpm=95, active=False),
            CueParams(pattern="rhythmic", bpm=102, active=False),
        ]
    )
    events: list[EventRecord] = Field(default_factory=list)
    phase: Phase = Phase.WALKING
    phase_label: str = PHASE_LABELS[Phase.WALKING]
    cue: CueInfo = Field(default_factory=lambda: CueInfo(bpm=95, active=False))
    recovery: RecoveryInfo = Field(default_factory=RecoveryInfo)
    edge: Classification = Field(
        default_factory=lambda: Classification(
            classification="walking", confidence=0.08, source="edge"
        )
    )
    runpod: RunPodResult = Field(default_factory=RunPodResult)
    analysis: Optional[GrokAnalysis] = None
    openai_post_event: Optional[OpenAIPostEvent] = None
    pending_next_cue: Optional[CueParams] = None
    disclaimer: str = (
        "RESEARCH / ASSISTIVE TECHNOLOGY PROTOTYPE — not a validated medical device. "
        "Signals describe possible freeze-like events, never confirmed freezing of gait."
    )


class ConnectionStatus(BaseModel):
    esp32: Literal["CONNECTED", "DEMO"] = "DEMO"
    runpod: Literal["ONLINE", "MOCK", "ERROR"] = "MOCK"
    grok: Literal["ONLINE", "MOCK", "ERROR"] = "MOCK"


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "fog-cueing-dashboard"
    disclaimer: str = (
        "Research prototype, not a medical device. No diagnosis or treatment claims."
    )
    phase: Phase = Phase.WALKING
    connections: ConnectionStatus = Field(default_factory=ConnectionStatus)
