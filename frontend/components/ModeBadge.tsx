"use client";

import type { DemoState, SensorMode } from "@/types";

const SOURCES: SensorMode[] = ["DEMO", "REPLAY", "LIVE"];

export default function ModeBadge({ state, onSource }: { state: DemoState; onSource: (s: SensorMode) => void }) {
  const { source, phase, running, replay, connections } = state;
  let status: string;
  let ok = true;
  if (source === "DEMO") status = phase === "IDLE" ? "READY" : running ? "EVENT RUNNING" : phase === "OUTCOME" ? "OUTCOME LEARNED" : "WALKING";
  else if (source === "REPLAY") status = replay.playing ? "REPLAYING LABELED DATA" : replay.finished ? "EVENT COMPLETE" : "LABELED DATA";
  else {
    ok = connections.esp32 === "CONNECTED";
    status = ok ? "DEVICE CONNECTED" : connections.socket === "open" ? "WAITING FOR DEVICE" : "NO BACKEND STREAM";
  }

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 rounded-full border border-white/10 bg-black/30 px-3 py-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? "phase-bg shadow-[0_0_8px_var(--phase)]" : "bg-signal-amber shadow-[0_0_8px_#ffb020]"}`} />
        <span className="value-display text-sm font-semibold tracking-wider text-white">
          {source} MODE <span className="text-white/35">·</span> {status}
        </span>
      </div>
      <div className="seg" role="tablist" aria-label="Data source">
        {SOURCES.map((s) => (
          <button key={s} type="button" role="tab" aria-selected={source === s} className={source === s ? "on" : ""} onClick={() => onSource(s)} disabled={running}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
