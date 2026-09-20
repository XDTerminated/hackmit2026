"use client";

import { useState } from "react";
import { API_URL, WS_URL } from "@/lib/services";
import type { DemoState, IMUSample } from "@/types";

export default function AdvancedPanel({ state, latest }: { state: DemoState; latest: IMUSample | null }) {
  const [open, setOpen] = useState(false);
  const c = state.connections;
  const lastEvent = state.events.at(-1);
  const rows: [string, string][] = [
    ["Phase (raw)", `${state.phase} · running=${state.running ? "yes" : "no"}`],
    ["Data source", state.source + (state.replay.loaded && state.source === "REPLAY" ? ` · ${state.replay.loaded.event_id}` : "")],
    ["Edge model", `edge-imu-v0 · ${state.edge.latency_ms} ms on-device`],
    ["RunPod model", `${state.runpod.model_version} · ${state.runpod.status}`],
    ["Grok", state.analysis ? (state.analysis.mock ? "mock (local evidence summary)" : "live") : "idle"],
    ["Cue", `${state.cue.pattern} · ${state.cue.bpm} BPM · source ${state.cue.source} · allowed ${state.allowed_next_cues.map((x) => x.bpm).join("/")}`],
    ["Backend", c.backendReachable ? `reachable · ${API_URL}` : `not reachable · ${API_URL} (demo continues locally)`],
    ["WebSocket", `${WS_URL} · ${c.socket} · attempts ${c.socketAttempts}${c.lastMessageAt ? ` · last msg ${new Date(c.lastMessageAt).toLocaleTimeString()}` : ""}`],
    ["ESP32", c.esp32],
    ["Motor control", "local / edge only — cloud never commands the actuator"],
  ];
  if (state.source === "REPLAY" && state.replay.loaded) {
    const r = state.replay.loaded;
    rows.push(["Replay markers", `detection ${r.markers.detection_t}s (${r.markers_source.detection}) · cue ${r.markers.cue_t}s (${r.markers_source.cue}) · recovery ${r.markers.recovery_t}s (${r.markers_source.recovery})`]);
  }

  return (
    <section className="card">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-5 py-2.5 text-left">
        <span className="label">Advanced · raw sensor, event JSON, models, connections</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-white/45">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="grid grid-cols-1 gap-4 border-t border-white/[0.07] px-5 py-4 lg:grid-cols-3">
          <dl className="space-y-1.5">
            {rows.map(([k, v]) => (
              <div key={k} className="border-b border-white/[0.05] pb-1.5">
                <dt className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/40">{k}</dt>
                <dd className="break-words font-mono text-[11px] text-white/80">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="space-y-3">
            <div>
              <p className="label">Raw sensor (latest)</p>
              <pre className="mt-1 overflow-x-auto rounded-lg bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-white/75">
                {latest ? JSON.stringify(fmtSample(latest), null, 1) : "—"}
              </pre>
            </div>
            <div>
              <p className="label">Last event JSON</p>
              <pre className="mt-1 max-h-56 overflow-auto rounded-lg bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-white/75">
                {lastEvent ? JSON.stringify(lastEvent, null, 1) : "—"}
              </pre>
            </div>
          </div>
          <div>
            <p className="label">Full Grok analysis</p>
            <pre className="mt-1 max-h-[26rem] overflow-auto whitespace-pre-wrap rounded-lg bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-white/75">
              {state.analysis?.full_analysis ?? "—"}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}

function fmtSample(s: IMUSample) {
  const r = (v: number | null | undefined) => (v == null ? null : Math.round(v * 1000) / 1000);
  return { t_ms: s.timestamp, ax: r(s.ax), ay: r(s.ay), az: r(s.az), gx: r(s.gx), gy: r(s.gy), gz: r(s.gz), accel_mag: r(s.accel_mag), gyro_mag: r(s.gyro_mag) };
}
