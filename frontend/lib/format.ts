import type { Phase } from "@/types";

export function pct(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

export function seconds(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return `${(ms / 1000).toFixed(2)} s`;
}

export const PHASE_LABEL: Record<Phase, string> = {
  IDLE: "READY",
  WALKING: "WALKING",
  POSSIBLE_FREEZE: "POSSIBLE FREEZE",
  DETECTED: "DETECTED",
  CUE_TRIGGERED: "HAPTIC CUE",
  RECOVERY_MONITORING: "RECOVERING",
  RECOVERED: "RECOVERED",
  ANALYZING: "ANALYZING",
  OUTCOME: "OUTCOME LEARNED",
};

export const PHASE_CLASS: Record<Phase, string> = {
  IDLE: "phase-idle",
  WALKING: "phase-walking",
  POSSIBLE_FREEZE: "phase-freeze",
  DETECTED: "phase-detected",
  CUE_TRIGGERED: "phase-cue",
  RECOVERY_MONITORING: "phase-recover",
  RECOVERED: "phase-recovered",
  ANALYZING: "phase-analyze",
  OUTCOME: "phase-outcome",
};

export const PHASE_COLOR: Record<Phase, string> = {
  IDLE: "#8fa3b8",
  WALKING: "#3ee0ff",
  POSSIBLE_FREEZE: "#ffb020",
  DETECTED: "#ff6a3d",
  CUE_TRIGGERED: "#ff4d6d",
  RECOVERY_MONITORING: "#2dd4bf",
  RECOVERED: "#b6ff4a",
  ANALYZING: "#c084fc",
  OUTCOME: "#7dd3fc",
};

export const PHASE_CAPTION: Record<Phase, string> = {
  IDLE: "Press START DEMO to begin.",
  WALKING: "Gait nominal. On-device detector watching the ankle signal.",
  POSSIBLE_FREEZE: "Step rhythm breaking up. Freeze-like pattern scored on-device.",
  DETECTED: "Edge threshold reached. Cloud verification requested.",
  CUE_TRIGGERED: "Rhythmic haptic cue from the ankle wearable.",
  RECOVERY_MONITORING: "Timing the return to baseline step rhythm.",
  RECOVERED: "Step rhythm restored. Episode logged.",
  ANALYZING: "Comparing this outcome with previous episodes.",
  OUTCOME: "Outcome logged and used to shape the next experiment.",
};

/** SENSE → DETECT → CUE → RECOVER → ADAPT */
export const STORY = ["SENSE", "DETECT", "CUE", "RECOVER", "ADAPT"] as const;
