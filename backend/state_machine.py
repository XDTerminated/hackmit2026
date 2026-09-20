"""Local/edge-first intervention state machine.

Grok and RunPod never transition the actuator. Cue dispatch is a local
decision from the edge detector (or an explicit demo/operator command).
"""

from __future__ import annotations

from models import PHASE_LABELS, Phase


# Legal local transitions. ANALYZING always returns to WALKING.
TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.WALKING: {Phase.POSSIBLE_FREEZE, Phase.CUE_TRIGGERED, Phase.WALKING},
    Phase.POSSIBLE_FREEZE: {
        Phase.DETECTED,
        Phase.CUE_TRIGGERED,
        Phase.WALKING,
        Phase.RECOVERY_MONITORING,
        Phase.POSSIBLE_FREEZE,
    },
    Phase.DETECTED: {Phase.CUE_TRIGGERED, Phase.WALKING, Phase.DETECTED},
    Phase.CUE_TRIGGERED: {Phase.RECOVERY_MONITORING, Phase.WALKING, Phase.CUE_TRIGGERED},
    Phase.RECOVERY_MONITORING: {
        Phase.RECOVERED,
        Phase.WALKING,
        Phase.RECOVERY_MONITORING,
    },
    Phase.RECOVERED: {Phase.ANALYZING, Phase.WALKING, Phase.RECOVERED},
    Phase.ANALYZING: {Phase.WALKING, Phase.ANALYZING},
}

DISPLAY_LABELS = PHASE_LABELS

LOOP_STEP: dict[Phase, str] = {
    Phase.WALKING: "SENSE",
    Phase.POSSIBLE_FREEZE: "DETECT",
    Phase.DETECTED: "DETECT",
    Phase.CUE_TRIGGERED: "INTERVENE",
    Phase.RECOVERY_MONITORING: "MEASURE RECOVERY",
    Phase.RECOVERED: "MEASURE RECOVERY",
    Phase.ANALYZING: "ANALYZE → ADAPT",
}


class StateMachine:
    def __init__(self, phase: Phase = Phase.WALKING) -> None:
        self.phase = phase

    def can_enter(self, nxt: Phase) -> bool:
        return nxt in TRANSITIONS[self.phase] or nxt == self.phase

    def enter(self, nxt: Phase) -> Phase:
        if nxt == self.phase:
            return self.phase
        if nxt not in TRANSITIONS[self.phase]:
            # Demo/reset may force WALKING from anywhere.
            if nxt is Phase.WALKING:
                self.phase = Phase.WALKING
                return self.phase
            raise ValueError(f"Illegal transition {self.phase.value} → {nxt.value}")
        self.phase = nxt
        return self.phase

    def force(self, nxt: Phase) -> Phase:
        self.phase = nxt
        return self.phase

    @property
    def label(self) -> str:
        return DISPLAY_LABELS[self.phase]

    @property
    def loop_step(self) -> str:
        return LOOP_STEP[self.phase]
