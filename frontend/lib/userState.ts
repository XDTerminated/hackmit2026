import type { Phase } from "@/types";

export const USER_PHASE: Record<Phase, { title: string; detail: string; tone: string }> = {
  IDLE: { title: "Ready when you are", detail: "Start monitoring to follow your walking.", tone: "calm" },
  WALKING: { title: "Monitoring your gait", detail: "Your wearable is following your walking.", tone: "calm" },
  POSSIBLE_FREEZE: { title: "Possible interruption", detail: "Checking movement.", tone: "attention" },
  DETECTED: { title: "Possible interruption", detail: "A rhythmic cue is starting.", tone: "attention" },
  CUE_TRIGGERED: { title: "Rhythmic cue active", detail: "Follow the rhythm if it helps.", tone: "cue" },
  RECOVERY_MONITORING: { title: "Movement resuming", detail: "Your walking is being observed.", tone: "recovery" },
  RECOVERED: { title: "Walking resumed", detail: "Your walking rhythm returned.", tone: "recovered" },
  ANALYZING: { title: "Session updated", detail: "Still learning your response.", tone: "calm" },
  OUTCOME: { title: "Monitoring your gait", detail: "Your wearable is following your walking.", tone: "calm" },
};
