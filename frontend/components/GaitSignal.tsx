"use client";

import type { MutableRefObject } from "react";
import type { IMUSample, Phase, SensorMode } from "@/types";
import type { ReplayEvent, ReplayIndex, SignalMarker } from "@/lib/datasources/types";
import Waveform, { type LabeledRegion } from "./Waveform";

export default function GaitSignal({
  samplesRef,
  cadence,
  baseline,
  phase,
  color,
  source,
  markers,
  replay,
  replayIndex,
  deviceConnected,
}: {
  samplesRef: MutableRefObject<IMUSample[]>;
  cadence: number;
  baseline: number;
  phase: Phase;
  color: string;
  source: SensorMode;
  markers: SignalMarker[];
  replay: ReplayEvent | null;
  replayIndex: ReplayIndex | null;
  deviceConnected: boolean;
}) {
  const freeze = phase === "POSSIBLE_FREEZE" || phase === "DETECTED" || phase === "CUE_TRIGGERED";
  const status =
    phase === "IDLE"
      ? source === "LIVE" && !deviceConnected
        ? "Waiting for device"
        : "Standby"
      : freeze
        ? "Freeze-like pattern"
        : phase === "RECOVERY_MONITORING"
          ? "Rhythm returning"
          : "Rhythmic stepping";

  const regions: LabeledRegion[] =
    source === "REPLAY" && replay?.fog_onset_t != null && replay.fog_offset_t != null
      ? [{ from_ms: replay.fog_onset_t * 1000, to_ms: replay.fog_offset_t * 1000, label: "LABELED FoG · FoG-STAR" }]
      : [];

  const ds = replayIndex?.dataset;

  return (
    <section className="card flex h-full flex-col overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div>
          <p className="label">{source === "REPLAY" ? "Replay gait signal" : "Live gait signal"}</p>
          <h3 className="value-display text-xl font-semibold text-white">
            ACCELERATION MAGNITUDE <span className="text-white/35">· ankle IMU</span>
          </h3>
        </div>
        <div className="flex gap-5">
          <Readout label="Cadence" value={cadence > 1 ? cadence.toFixed(0) : "—"} unit="BPM" hot={freeze} />
          <Readout label="Baseline" value={baseline.toFixed(0)} unit="BPM" />
          <Readout label="Sensor" value={source} />
        </div>
      </div>

      <div className="relative mt-1 min-h-[190px] flex-1">
        <Waveform
          samplesRef={samplesRef}
          color={color}
          markers={markers}
          regions={regions}
          windowMs={10000}
          emptyLabel={source === "LIVE" ? "WAITING FOR ESP32 STREAM" : source === "REPLAY" ? "SELECT A LABELED EVENT AND PRESS REPLAY" : "STANDBY"}
        />
        <div className="pointer-events-none absolute left-5 top-7 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-white/50">
          <span className="live-dot" />
          {status}
        </div>
      </div>

      {/* data credibility strip */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/[0.06] px-5 py-2 font-mono text-[9.5px] uppercase tracking-[0.18em] text-white/45">
        <span className="text-white/70">Data</span>
        {source === "REPLAY" && ds ? (
          <>
            <span className="text-white/80">{ds.name} replay</span>
            <span>{ds.participants} PD participants</span>
            <span>{ds.sample_rate_hz} Hz ankle IMU</span>
            <span>acc + gyro</span>
            <span>{ds.labels}</span>
            <span className="text-signal-amber">Detection/cue overlay simulated · recovery is labeled FoG offset</span>
            {replay && (
              <span className="ml-auto text-white/60">
                {replay.subject_id} · {replay.task} · {replay.fog_severity ?? "FoG"} · {replay.sensor.split(" ")[0]}
              </span>
            )}
          </>
        ) : source === "LIVE" ? (
          <>
            <span className="text-white/80">ESP32 ankle IMU stream</span>
            <span>{deviceConnected ? "device connected" : "no device — switch to DEMO or REPLAY"}</span>
          </>
        ) : (
          <>
            <span className="text-white/80">Synthetic gait generator</span>
            <span>step-pulse model · jittered timing + amplitude</span>
            <span>freeze-like tremor + stalls</span>
            {ds && <span className="ml-auto text-white/60">labeled replay available: {ds.name}</span>}
          </>
        )}
      </div>
    </section>
  );
}

function Readout({ label, value, unit, hot }: { label: string; value: string; unit?: string; hot?: boolean }) {
  return (
    <div className="text-right">
      <p className="label">{label}</p>
      <p className={`value-display text-[26px] font-semibold leading-none ${hot ? "phase-text" : "text-white"}`}>
        {value}
        {unit && <span className="ml-1 text-xs text-white/40">{unit}</span>}
      </p>
    </div>
  );
}
