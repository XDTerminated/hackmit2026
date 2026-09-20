import type { IMUSample } from "@/types";

export type GaitMode = "idle" | "walking" | "freeze" | "recovering";

interface Step {
  onset: number; // s
  amp: number; // relative 0..1.3
  interval: number; // s to the next step
}

const G = 9.81;
const WALK_AMP = 2.4; // m/s² peak-to-baseline for a full-amplitude heel strike

/**
 * Procedural, IMU-like gait generator (client-side, deterministic timing).
 *
 * Rather than an oscillator, the signal is a sum of discrete step pulses whose
 * onset interval and amplitude are jittered per step, plus slow baseline drift
 * and sensor noise. Freeze-like mode replaces steps with hesitant micro-steps,
 * bursty 5–7 Hz trembling and short flat stalls. Recovery interpolates step
 * regularity and amplitude back toward baseline over ~1.6 s.
 */
export class GaitSim {
  baseline: number;
  mode: GaitMode = "idle";

  private t0 = performance.now();
  private t = 0;
  private lastT = 0;
  private steps: Step[] = [];
  private nextStepAt = 0.35;
  private drift = 0;
  private freezeDepth = 0; // 0..1 how far into freeze-like behaviour
  private recover = 1; // 0..1 regularity during recovery
  private tremorPhase = 0;
  private tremorHz = 6;
  private tremorEnv = 0;
  private tremorTarget = 0;
  private tremorSwitchAt = 0;
  private cadenceEst = 0;

  constructor(baseline = 102) {
    this.baseline = baseline;
  }

  setMode(mode: GaitMode) {
    if (mode === this.mode) return;
    if (mode === "recovering") this.recover = 0.05;
    if (mode === "walking" && this.mode === "idle") {
      this.recover = 1;
      this.nextStepAt = this.t + 0.2;
    }
    this.mode = mode;
  }

  reset(baseline?: number) {
    if (baseline) this.baseline = baseline;
    this.mode = "idle";
    this.t0 = performance.now();
    this.t = 0;
    this.lastT = 0;
    this.steps = [];
    this.nextStepAt = 0.35;
    this.drift = 0;
    this.freezeDepth = 0;
    this.recover = 1;
    this.tremorEnv = 0;
    this.tremorTarget = 0;
    this.tremorSwitchAt = 0;
    this.cadenceEst = 0;
  }

  /** Estimated cadence (steps/min) from recent step intervals, weighted by step quality. */
  get cadence(): number {
    return this.cadenceEst;
  }

  sample(): IMUSample {
    const now = (performance.now() - this.t0) / 1000;
    const dt = Math.max(0.001, Math.min(0.2, now - this.lastT));
    this.lastT = now;
    this.t = now;
    const t = this.t;

    // ---- mode envelopes
    const freezeTarget = this.mode === "freeze" ? 1 : 0;
    this.freezeDepth += (freezeTarget - this.freezeDepth) * Math.min(1, dt * (freezeTarget ? 4 : 1.6));
    if (this.mode === "recovering") {
      this.recover = Math.min(1, this.recover + dt / 1.6);
      if (this.recover >= 1) this.mode = "walking";
    }
    const regularity = this.mode === "walking" ? 1 : this.mode === "recovering" ? this.recover : 0;

    // ---- step scheduler
    if (this.mode !== "idle" && t >= this.nextStepAt) {
      let interval: number;
      let amp: number;
      if (this.mode === "freeze") {
        // hesitant micro-steps, irregular, sometimes skipped (stall)
        interval = 0.32 + Math.random() * 0.6;
        amp = Math.random() < 0.35 ? 0 : 0.08 + Math.random() * 0.16;
      } else {
        const nominal = 60 / this.baseline;
        const jitter = 0.035 + 0.14 * (1 - regularity);
        interval = nominal * (1 + jitter * gauss(1));
        interval = Math.max(0.32, Math.min(1.2, interval));
        amp = (1 + 0.11 * gauss(1)) * (0.3 + 0.7 * regularity);
        // occasional slightly heavier / lighter strike
        if (Math.random() < 0.08) amp *= 1.18;
      }
      this.steps.push({ onset: t, amp, interval });
      if (this.steps.length > 4) this.steps.shift();
      this.nextStepAt = t + interval;

      // cadence estimate from the last few intervals, discounted by step quality
      const recent = this.steps.slice(-3);
      const meanInt = recent.reduce((a, s) => a + s.interval, 0) / recent.length;
      const quality = Math.min(1, (recent.reduce((a, s) => a + s.amp, 0) / recent.length) / 0.55);
      const est = (60 / meanInt) * quality;
      this.cadenceEst += (est - this.cadenceEst) * 0.45;
    }
    if (this.mode === "idle") this.cadenceEst += (0 - this.cadenceEst) * Math.min(1, dt * 3);
    if (this.mode === "freeze" && t - (this.steps.at(-1)?.onset ?? 0) > 0.9) {
      this.cadenceEst += (12 - this.cadenceEst) * Math.min(1, dt * 1.5);
    }

    // ---- step pulse synthesis
    let pulse = 0;
    let gyro = 0;
    for (const s of this.steps) {
      const tau = t - s.onset;
      if (tau < 0 || tau > s.interval * 1.1) continue;
      const I = s.interval;
      const A = s.amp * WALK_AMP;
      pulse +=
        A *
        (1.0 * bell(tau, 0.0, 0.045) + // heel strike
          0.22 * bell(tau, 0.16 * I, 0.06) + // loading response
          0.55 * bell(tau, 0.4 * I, 0.09) - // push-off
          0.38 * bell(tau, 0.66 * I, 0.11)); // swing unloading
      gyro += s.amp * 165 * bell(tau, 0.55 * I, 0.14 * I) + s.amp * 60 * bell(tau, 0.05, 0.05);
    }

    // ---- freeze-like trembling with bursts and stalls
    if (this.freezeDepth > 0.02) {
      if (t >= this.tremorSwitchAt) {
        const stall = Math.random() < 0.38;
        this.tremorTarget = stall ? 0 : 0.35 + Math.random() * 0.65;
        this.tremorSwitchAt = t + (stall ? 0.25 + Math.random() * 0.45 : 0.3 + Math.random() * 0.7);
        this.tremorHz = 5.2 + Math.random() * 2.2;
      }
      this.tremorEnv += (this.tremorTarget - this.tremorEnv) * Math.min(1, dt * 9);
      this.tremorPhase += 2 * Math.PI * this.tremorHz * dt;
      const env = this.tremorEnv * this.freezeDepth * (1 - regularity * 0.85);
      const shape = Math.sin(this.tremorPhase) + 0.35 * Math.sin(2 * this.tremorPhase + 0.7);
      pulse += 0.5 * env * shape;
      gyro += 55 * env * Math.abs(shape);
    }

    // ---- slow baseline drift + sensor noise
    this.drift = Math.max(-0.22, Math.min(0.22, this.drift * 0.999 + gauss(0.0045)));
    const noise = gauss(0.035);
    const accelMag = G + this.drift + pulse + noise;
    const gyroMag = Math.max(0, gyro + gauss(1.6) + 2);

    const az = accelMag;
    const ax = 0.08 * pulse + gauss(0.02);
    const ay = -0.12 * pulse + gauss(0.02);

    return {
      timestamp: Math.round(t * 1000),
      ax,
      ay,
      az,
      gx: gyroMag * 0.8,
      gy: gyroMag * 0.5,
      gz: gyroMag * 0.3,
      accel_mag: accelMag,
      gyro_mag: gyroMag,
      cadence_bpm: Math.max(0, this.cadenceEst),
    };
  }
}

function bell(x: number, mu: number, sigma: number): number {
  const z = (x - mu) / sigma;
  return Math.exp(-0.5 * z * z);
}

function gauss(sd: number): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
