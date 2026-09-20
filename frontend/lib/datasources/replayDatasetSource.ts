import type { IMUSample } from "@/types";
import type { DataSource, ReplayEvent, ReplayIndex, SampleSink } from "./types";

const G = 9.81;

export const REPLAY_INDEX_URL = "/data/replay/index.json";

export async function loadReplayIndex(): Promise<ReplayIndex | null> {
  try {
    const res = await fetch(REPLAY_INDEX_URL, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as ReplayIndex;
  } catch {
    return null;
  }
}

export async function loadReplayEvent(file: string): Promise<ReplayEvent | null> {
  try {
    const res = await fetch(`/data/replay/${file}`, { cache: "force-cache" });
    if (!res.ok) return null;
    const ev = (await res.json()) as ReplayEvent;
    if (!Array.isArray(ev.samples) || ev.samples.length < 10) return null;
    return ev;
  } catch {
    return null;
  }
}

/**
 * Plays a prepared labeled IMU window (e.g. a FoG-STAR episode) in real time.
 * Emits IMUSamples on the common sink and reports replay time so the engine can
 * sync state changes with the event markers.
 */
export class ReplayDatasetSource implements DataSource {
  readonly kind = "REPLAY" as const;
  private raf = 0;
  private startedAt = 0;
  private idx = 0;
  private running = false;

  constructor(
    readonly event: ReplayEvent,
    private readonly onTick: (tSec: number) => void,
    private readonly onEnd: () => void,
  ) {}

  start(sink: SampleSink) {
    this.stop();
    this.running = true;
    this.idx = 0;
    this.startedAt = performance.now();
    const samples = this.event.samples;
    const loop = () => {
      if (!this.running) return;
      const elapsed = (performance.now() - this.startedAt) / 1000;
      while (this.idx < samples.length && samples[this.idx].t <= elapsed) {
        sink(toIMU(samples[this.idx]));
        this.idx++;
      }
      this.onTick(Math.min(elapsed, this.event.duration_s));
      if (this.idx >= samples.length) {
        this.running = false;
        this.onEnd();
        return;
      }
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }
}

function toIMU(s: { t: number; acc_mag: number; gyro_mag: number }): IMUSample {
  const accel = s.acc_mag * G;
  return {
    timestamp: Math.round(s.t * 1000),
    ax: 0,
    ay: 0,
    az: accel,
    gx: s.gyro_mag,
    gy: 0,
    gz: 0,
    accel_mag: accel,
    gyro_mag: s.gyro_mag,
    cadence_bpm: null,
  };
}
