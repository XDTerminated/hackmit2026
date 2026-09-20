"use client";

import Link from "next/link";
import GaitFigure from "@/components/GaitFigure";
import UserShell from "@/components/UserShell";
import Waveform from "@/components/Waveform";
import { useSharedSession } from "@/lib/useSharedSession";
import { USER_PHASE } from "@/lib/userState";

const timeline = ["SENSE", "DETECT", "CUE", "RECOVER"] as const;

function formatRecovery(ms: number | null | undefined) {
  return ms == null ? "—" : `${(ms / 1000).toFixed(2)} s`;
}

function timeLabel(iso?: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export default function HomePage() {
  const { state, monitoring, cadence, samplesRef, startMonitoring, stopMonitoring, triggerFreeze } = useSharedSession();
  const view = USER_PHASE[state.phase];
  const hasCadence = cadence > 1;
  const latestEvent = state.events.filter((event) => !event.episode_id.startsWith("R")).at(-1);
  const activeTimelineIndex = state.phase === "WALKING" ? 0 : state.phase === "POSSIBLE_FREEZE" || state.phase === "DETECTED" ? 1 : state.phase === "CUE_TRIGGERED" ? 2 : 3;
  const signalColor = state.phase === "CUE_TRIGGERED" ? "#ef9cae" : state.phase === "POSSIBLE_FREEZE" || state.phase === "DETECTED" ? "#edba76" : state.phase === "RECOVERED" ? "#b9e989" : "#8fe8db";
  const signalDescription = state.phase === "POSSIBLE_FREEZE" || state.phase === "DETECTED" || state.phase === "CUE_TRIGGERED" ? "Rhythm disrupted" : state.phase === "RECOVERY_MONITORING" || state.phase === "RECOVERED" ? "Rhythm returning" : "Steady steps";

  return (
    <UserShell title="Home" hideHeaderRight>
      <section className={`user-hero tone-${view.tone}`} aria-live="polite">
        <div className="user-figure"><GaitFigure phase={state.phase} cadence={cadence} baseline={state.baseline_cadence_bpm} cueActive={state.cue.active} cueBpm={state.cue.bpm} /></div>
        <div className="user-hero-copy"><p className="user-eyebrow">CURRENT STATE</p><h1>{view.title}</h1><p>{state.phase === "CUE_TRIGGERED" ? `${state.cue.bpm} BPM · experimental rhythmic cue` : state.phase === "RECOVERY_MONITORING" ? `${formatRecovery(state.recovery.elapsed_ms)} · measuring walking return` : view.detail}</p></div>
      </section>

      <section className="user-signal-card" aria-label="Live movement">
        <div className="user-card-heading"><div><p className="user-card-kicker"><span className="signal-live-dot" /> LIVE MOVEMENT</p><h2><span className="signal-state-pill" style={{ backgroundColor: signalColor }} />{signalDescription}</h2><p className="signal-cadence">{hasCadence ? `${Math.round(cadence)} BPM · measured cadence` : "Cadence unavailable"}</p></div><span className="user-card-meta">{hasCadence ? "MEASURED STREAM" : "WAITING FOR MEASURED DATA"}</span></div>
        <div className="user-mini-wave"><Waveform samplesRef={samplesRef} color={signalColor} markers={state.markers} phase={state.phase} minimal windowMs={3000} emptyLabel="WAITING FOR MOVEMENT SIGNAL" /></div>
      </section>

      <section className={`user-loop-card tone-${view.tone}`} aria-label="Closed loop">
        <div className="user-card-heading"><div><p className="user-card-kicker">{state.phase === "RECOVERY_MONITORING" || state.phase === "RECOVERED" ? "RECOVERY" : "RHYTHMIC CUE"}</p><h2>{state.phase === "CUE_TRIGGERED" ? `${state.cue.bpm} BPM` : state.phase === "RECOVERY_MONITORING" ? "Measuring return" : state.phase === "RECOVERED" ? `Walking resumed · ${formatRecovery(state.recovery.time_ms)}` : "Ready when needed"}</h2></div><span className="loop-status">{state.phase === "CUE_TRIGGERED" ? "Active" : state.phase === "RECOVERY_MONITORING" ? formatRecovery(state.recovery.elapsed_ms) : state.phase === "RECOVERED" ? "Complete" : "Automatic"}</span></div>
        <div className="user-timeline">{timeline.map((step, index) => { const done = state.phase === "RECOVERED" || state.phase === "ANALYZING" || index < activeTimelineIndex; const active = index === activeTimelineIndex && state.phase !== "WALKING"; return <div className={`user-timeline-step ${done ? "done" : ""} ${active ? "active" : ""}`} key={step}><span className="timeline-dot">{done ? "✓" : index + 1}</span><span>{step}</span></div>; })}</div>
      </section>

      {latestEvent ? <Link href="/activity" className="user-recent-card"><div><p className="user-card-kicker">RECENT ACTIVITY</p><h2>Walking resumed in {formatRecovery(latestEvent.recovery.time_ms)}</h2><p>Cue: {latestEvent.cue.bpm} BPM <span>·</span> {timeLabel(latestEvent.timestamp_iso)}</p></div><span className="user-chevron">›</span></Link> : <section className="user-recent-card user-empty-card"><p className="user-card-kicker">RECENT ACTIVITY</p><p>No interruptions recorded yet.</p></section>}

      <button className="user-primary" type="button" disabled={state.connections.socket !== "open"} onClick={monitoring ? stopMonitoring : startMonitoring}>{state.connections.socket !== "open" ? "Connecting…" : monitoring ? "Stop monitoring" : "Start monitoring"}</button>
      {state.source === "DEMO" && monitoring && <button className="user-demo-trigger" type="button" onClick={triggerFreeze} disabled={state.phase !== "WALKING"}>Simulate interruption <span>Demo control</span></button>}
    </UserShell>
  );
}
