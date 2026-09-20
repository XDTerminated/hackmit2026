import { GaitSim, type GaitMode } from "../gaitSim";
import type { DataSource, SampleSink } from "./types";

/** Synthetic-but-realistic gait at 25 Hz. Used for the judging demo. */
export class DemoSimulatorSource implements DataSource {
  readonly kind = "DEMO" as const;
  readonly sim: GaitSim;
  private timer: number | null = null;

  constructor(baseline = 102) {
    this.sim = new GaitSim(baseline);
  }

  start(sink: SampleSink) {
    this.stop();
    this.timer = window.setInterval(() => sink(this.sim.sample()), 40);
  }

  stop() {
    if (this.timer != null) window.clearInterval(this.timer);
    this.timer = null;
  }

  setGaitMode(mode: GaitMode) {
    this.sim.setMode(mode);
  }

  reset(baseline?: number) {
    this.sim.reset(baseline);
  }

  get cadence() {
    return this.sim.cadence;
  }
}
