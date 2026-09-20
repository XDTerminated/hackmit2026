"use client";

import { seconds } from "@/lib/format";
import type { DemoState } from "@/types";
import Gauge from "./Gauge";

export default function ResponsePanel({ state }: { state: DemoState }) {
  const { phase, edge, runpod, cue, recovery, events } = state;
  const timing = phase === "RECOVERY_MONITORING";
  const justRecovered = phase === "RECOVERED";
  const recoveryMs = timing ? recovery.elapsed_ms : recovery.time_ms;
  const pulseMs = Math.round(60000 / Math.max(40, cue.bpm));
  const focus =
    phase === "POSSIBLE_FREEZE" ? "detect"
    : phase === "DETECTED" ? "verify"
    : phase === "CUE_TRIGGERED" ? "cue"
    : timing || justRecovered ? "recovery"
    : null;
  const history = [...events].reverse().slice(0, 3);

  return (
    <section className="card flex h-full flex-col p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="label">Response</p>
          <h3 className="value-display text-xl font-semibold text-white">DETECT · CUE · RECOVER</h3>
        </div>
        {state.lastEpisodeId && (
          <span className="rounded-full bg-white/5 px-3 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-white/55">
            {state.lastEpisodeId}
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2">
        <Metric title="Detection" focus={focus === "detect"} sub={state.source === "REPLAY" ? "prototype overlay" : edge.confidence >= 0.6 ? "freeze-like" : edge.confidence >= 0.3 ? "uncertain" : "on-device"}>
          <Gauge value={edge.confidence} size={88} label="" />
        </Metric>

        <Metric
          title="Verification"
          focus={focus === "verify"}
          sub={runpod.status === "pending" ? "verifying…" : runpod.status === "idle" ? "idle" : runpod.classification === "freeze_like" ? "freeze-like" : "walking"}
        >
          <Gauge value={runpod.confidence} size={88} pending={runpod.status === "pending"} label="" />
        </Metric>

        <Metric title="Haptic cue" focus={focus === "cue"} sub={cue.active ? "rhythmic · active" : "rhythmic"} subHot={cue.active}>
          <div className="relative h-[88px] w-[88px]" style={{ ["--pulse-ms" as string]: `${pulseMs}ms` } as React.CSSProperties}>
            {cue.active && (
              <>
                <span className="ring absolute inset-2 rounded-full" />
                <span className="ring absolute inset-2 rounded-full" style={{ animationDelay: `${pulseMs / 2}ms` }} />
              </>
            )}
            <div
              className={`absolute inset-3 flex flex-col items-center justify-center rounded-full border ${cue.active ? "core-beat phase-border" : "border-white/15"}`}
              style={cue.active ? { boxShadow: "0 0 22px rgb(var(--phase-rgb) / 0.5)" } : undefined}
            >
              <span className="value-display text-[26px] font-bold leading-none text-white">{cue.bpm}</span>
              <span className="font-mono text-[8px] tracking-[0.2em] text-white/45">BPM</span>
            </div>
          </div>
        </Metric>

        <Metric
          title={state.source === "REPLAY" ? "Labeled offset" : justRecovered ? "Recovery detected" : "Recovery"}
          focus={focus === "recovery"}
          pop={justRecovered}
          sub={state.source === "REPLAY" ? "not a measured cue response" : recovery.detected ? "return to baseline" : timing ? "timing…" : "—"}
          subHot={recovery.detected}
        >
          <div className="flex h-[88px] flex-col items-center justify-center">
            <span className={`value-display font-bold leading-none ${timing || justRecovered ? "phase-text" : "text-white"} ${justRecovered ? "text-[40px]" : "text-[32px]"}`}>
              {recoveryMs == null ? "0.00 s" : seconds(recoveryMs)}
            </span>
          </div>
        </Metric>
      </div>

      {history.length > 0 && (
        <ul className="mt-3 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-2">
          {history.map((e) => (
            <li
              key={e.episode_id}
              className={`flex items-baseline justify-between rounded-md px-2 py-1 font-mono text-[11px] ${e.episode_id === state.lastEpisodeId ? "rise text-white" : "text-white/55"}`}
              style={e.episode_id === state.lastEpisodeId ? { background: "rgb(var(--phase-rgb) / 0.08)" } : undefined}
            >
              <span className="tracking-[0.12em]">{e.episode_id}</span>
              <span>{e.cue.bpm} BPM</span>
              <span className="value-display text-[13px]">{seconds(e.recovery.time_ms)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Metric({
  title,
  sub,
  subHot,
  focus,
  pop,
  children,
}: {
  title: string;
  sub: string;
  subHot?: boolean;
  focus: boolean;
  pop?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-xl border px-2 py-2 transition ${pop ? "pop" : ""} ${
        focus ? "border-[rgb(var(--phase-rgb)/0.5)] bg-[rgb(var(--phase-rgb)/0.08)]" : "border-white/[0.07] bg-white/[0.02]"
      }`}
    >
      <p className={`label self-start ${pop ? "phase-text" : ""}`}>{title}</p>
      <div className="my-1">{children}</div>
      <p className={`font-mono text-[9.5px] uppercase tracking-[0.18em] ${subHot ? "phase-text" : "text-white/50"}`}>{sub}</p>
    </div>
  );
}
