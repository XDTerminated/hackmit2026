export type Phase =
  | "IDLE"
  | "WALKING"
  | "POSSIBLE_FREEZE"
  | "DETECTED"
  | "CUE_TRIGGERED"
  | "RECOVERY_MONITORING"
  | "RECOVERED"
  | "ANALYZING"
  | "OUTCOME";

export type ClassificationLabel = "walking" | "freeze_like" | "unknown";

export interface IMUSample {
  timestamp: number;
  ax: number;
  ay: number;
  az: number;
  gx: number;
  gy: number;
  gz: number;
  accel_mag: number;
  gyro_mag: number;
  cadence_bpm?: number | null;
}

export interface EdgeScore {
  classification: ClassificationLabel;
  confidence: number;
  latency_ms: number;
}

export interface RunPodResult {
  classification: ClassificationLabel;
  confidence: number;
  model_version: string;
  status: "idle" | "pending" | "complete" | "mock" | "error";
}

export interface CueInfo {
  pattern: "rhythmic" | "pulse" | "off";
  bpm: number;
  active: boolean;
  source: "edge_local" | "operator";
}

export interface CueParams {
  pattern: "rhythmic" | "pulse" | "off";
  bpm: number;
}

export interface RecoveryInfo {
  detected: boolean;
  elapsed_ms: number;
  time_ms: number | null;
  pre_cadence: number;
  post_cadence: number | null;
}

export interface EventRecord {
  episode_id: string;
  timestamp_iso: string;
  edge: { classification: ClassificationLabel; confidence: number };
  runpod: RunPodResult;
  cue: CueInfo;
  recovery: { detected: boolean; time_ms: number | null };
  status: string;
  event_duration_ms: number | null;
  pre_cadence: number | null;
  post_cadence: number | null;
}

export interface GrokAnalysis {
  summary: string;
  observation: string;
  evidence: string;
  next_experiment: string;
  confidence_statement: string;
  full_analysis: string;
  session_summary: string;
  cue_comparison: string;
  observations: string;
  safety: string;
  limitation: string;
  recommended_cue?: CueParams | null;
  mock: boolean;
}

export interface OpenAIPostEvent {
  status: "online" | "not_configured" | "error";
  model: string;
  episode_id: string;
  summary: string;
  observation: string;
  recovery_seconds: number;
  cue_bpm: number;
  next_step: string;
  safety_note: string;
  error?: string | null;
}

export type ServiceMode = "MOCK" | "ONLINE";
export type SensorMode = "DEMO" | "LIVE" | "REPLAY";

export interface Connections {
  esp32: "CONNECTED" | "DISCONNECTED";
  socket: "connecting" | "open" | "closed";
  socketAttempts: number;
  lastMessageAt: number | null;
  runpod: ServiceMode;
  grok: ServiceMode;
  backendReachable: boolean;
}

export interface ReplayStatus {
  index: import("@/lib/datasources/types").ReplayIndex | null;
  selected: number;
  loaded: import("@/lib/datasources/types").ReplayEvent | null;
  playing: boolean;
  finished: boolean;
  loadError: boolean;
}

export interface DemoState {
  source: SensorMode;
  phase: Phase;
  running: boolean;
  storyStep: number;
  baseline_cadence_bpm: number;
  allowed_next_cues: CueParams[];
  edge: EdgeScore;
  runpod: RunPodResult;
  cue: CueInfo;
  recovery: RecoveryInfo;
  analysis: GrokAnalysis | null;
  openai_post_event: OpenAIPostEvent | null;
  events: EventRecord[];
  lastEpisodeId: string | null;
  markers: import("@/lib/datasources/types").SignalMarker[];
  replay: ReplayStatus;
  connections: Connections;
}
