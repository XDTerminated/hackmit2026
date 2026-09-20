import type { IMUSample } from "@/types";

export type DataSourceKind = "DEMO" | "REPLAY" | "LIVE";

export type SampleSink = (sample: IMUSample) => void;

/**
 * Common contract for anything that can feed the gait signal.
 * The UI and the demo engine never care which implementation is active.
 */
export interface DataSource {
  readonly kind: DataSourceKind;
  start(sink: SampleSink): void;
  stop(): void;
}

// ------------------------------------------------------------ replay files

export type MarkerKind = "DETECTION" | "CUE" | "RECOVERY";

export interface SignalMarker {
  t_ms: number; // on the sample timestamp axis
  kind: MarkerKind;
}

export interface ReplaySample {
  t: number; // seconds from window start
  acc_mag: number; // g
  gyro_mag: number; // deg/s
  fog?: 0 | 1; // dataset label for this sample, when available
}

export interface ReplayEvent {
  event_id: string;
  source: string;
  title: string;
  subject_id: string;
  session_id?: string;
  task: string;
  label: "freeze_like" | "walking";
  fog_severity?: string | null;
  sensor: string;
  sample_rate_hz: number;
  baseline_cadence_bpm: number;
  duration_s: number;
  fog_onset_t?: number | null;
  fog_offset_t?: number | null;
  markers: { detection_t: number; cue_t: number; recovery_t: number };
  markers_source: { detection: string; cue: string; recovery: string };
  samples: ReplaySample[];
}

export interface ReplayEventMeta {
  event_id: string;
  title: string;
  file: string;
  subject_id: string;
  task: string;
  fog_severity?: string | null;
  duration_s: number;
}

export interface ReplayIndex {
  dataset: {
    name: string;
    participants: number;
    sample_rate_hz: number;
    sensors: string;
    labels: string;
    citation?: string;
    url?: string;
  };
  events: ReplayEventMeta[];
}
