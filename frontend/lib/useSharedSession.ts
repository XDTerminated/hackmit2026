"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, WS_URL } from "./services";
import { loadReplayEvent, loadReplayIndex } from "./datasources/replayDatasetSource";
import type { DemoState, EventRecord, IMUSample, Phase, SensorMode } from "@/types";
import type { SignalMarker } from "./datasources/types";

const initial: DemoState = {
  source: "DEMO", phase: "IDLE", running: false, storyStep: 0,
  baseline_cadence_bpm: 102, allowed_next_cues: [{ pattern: "rhythmic", bpm: 80 }, { pattern: "rhythmic", bpm: 95 }, { pattern: "rhythmic", bpm: 102 }],
  edge: { classification: "walking", confidence: 0.08, latency_ms: 18 },
  runpod: { classification: "unknown", confidence: 0, model_version: "mock-imu-v0", status: "idle" },
  cue: { pattern: "rhythmic", bpm: 95, active: false, source: "edge_local" },
  recovery: { detected: false, elapsed_ms: 0, time_ms: null, pre_cadence: 102, post_cadence: null },
  analysis: null, openai_post_event: null, events: [], lastEpisodeId: null, markers: [],
  replay: { index: null, selected: 0, loaded: null, playing: false, finished: false, loadError: false },
  connections: { esp32: "DISCONNECTED", socket: "connecting", socketAttempts: 0, lastMessageAt: null, runpod: "MOCK", grok: "MOCK", backendReachable: false },
};

type ServerSession = {
  monitoring: boolean; source: SensorMode; phase: Phase; baseline_cadence_bpm: number;
  current_cadence_bpm: number; allowed_next_cues: DemoState["allowed_next_cues"];
  edge: DemoState["edge"]; runpod: DemoState["runpod"]; cue: DemoState["cue"];
  recovery: DemoState["recovery"]; events: EventRecord[]; analysis: DemoState["analysis"]; openai_post_event: DemoState["openai_post_event"];
};

async function command(path: string, body?: unknown, method = "POST") {
  const response = await fetch(`${API_URL}${path}`, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) throw new Error(`Command failed: ${path}`);
  return response.json();
}

export function useSharedSession() {
  const [state, setState] = useState<DemoState>(initial);
  const [cadence, setCadence] = useState(0);
  const [latest, setLatest] = useState<IMUSample | null>(null);
  const [monitoring, setMonitoring] = useState(false);
  const samplesRef = useRef<IMUSample[]>([]);
  const stateRef = useRef(state);
  const lastPhase = useRef<Phase>("IDLE");
  const lastUi = useRef(0);
  stateRef.current = state;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let active = true;
    const connect = () => {
      if (!active) return;
      socket = new WebSocket(WS_URL);
      setState((s) => ({ ...s, connections: { ...s.connections, socket: "connecting", socketAttempts: s.connections.socketAttempts + 1 } }));
      socket.onopen = () => setState((s) => ({ ...s, connections: { ...s.connections, socket: "open", backendReachable: true } }));
      socket.onclose = () => {
        setState((s) => ({ ...s, connections: { ...s.connections, socket: "closed", backendReachable: false } }));
        if (active) retry = setTimeout(connect, 1500);
      };
      socket.onmessage = (message) => {
        let payload: { type: string; data: any };
        try { payload = JSON.parse(message.data); } catch { return; }
        const d = payload.data;
        if (payload.type === "signal_reset") {
          samplesRef.current = [];
          lastPhase.current = "IDLE";
          setLatest(null);
          setCadence(0);
          setState((s) => ({ ...s, markers: [] }));
          return;
        }
        if (payload.type === "imu") {
          samplesRef.current.push(d as IMUSample);
          if (samplesRef.current.length > 1500) samplesRef.current.splice(0, samplesRef.current.length - 1500);
          if (performance.now() - lastUi.current > 160) {
            lastUi.current = performance.now();
            setLatest(d);
            if (typeof d.cadence_bpm === "number") setCadence(d.cadence_bpm);
          }
          return;
        }
        if (payload.type === "session") {
          const x = d as ServerSession;
          if (!x.monitoring) {
            samplesRef.current = [];
            setLatest(null);
            setCadence(0);
          }
          setMonitoring(x.monitoring);
          setState((s) => ({ ...s, source: x.source, phase: x.monitoring ? x.phase : "IDLE", running: x.monitoring && !["WALKING", "IDLE"].includes(x.phase), baseline_cadence_bpm: x.baseline_cadence_bpm, allowed_next_cues: x.allowed_next_cues, edge: { ...s.edge, ...x.edge }, runpod: x.runpod, cue: x.cue, recovery: x.recovery, events: x.events, lastEpisodeId: x.events.at(-1)?.episode_id ?? null, analysis: x.analysis, openai_post_event: x.openai_post_event, replay: { ...s.replay, playing: x.source === "REPLAY" && x.monitoring, finished: x.source === "REPLAY" && !x.monitoring && s.replay.loaded !== null } }));
          return;
        }
        if (payload.type === "state") {
          const phase = d.phase as Phase;
          if (phase !== lastPhase.current) {
            const kind: SignalMarker["kind"] | null = phase === "DETECTED" ? "DETECTION" : phase === "CUE_TRIGGERED" ? "CUE" : phase === "RECOVERED" ? "RECOVERY" : null;
            if (kind) setState((s) => ({ ...s, markers: [...s.markers, { kind, t_ms: samplesRef.current.at(-1)?.timestamp ?? 0 }] }));
            lastPhase.current = phase;
          }
          setState((s) => ({ ...s, phase, running: !["WALKING", "IDLE"].includes(phase), storyStep: phase === "POSSIBLE_FREEZE" || phase === "DETECTED" ? 1 : phase === "CUE_TRIGGERED" ? 2 : phase === "RECOVERY_MONITORING" || phase === "RECOVERED" ? 3 : phase === "ANALYZING" ? 4 : s.storyStep }));
        } else if (payload.type === "detection") setState((s) => ({ ...s, edge: { ...s.edge, ...d.edge }, runpod: d.runpod }));
        else if (payload.type === "cue") setState((s) => ({ ...s, cue: d }));
        else if (payload.type === "recovery") setState((s) => ({ ...s, recovery: d }));
        else if (payload.type === "analysis") setState((s) => ({ ...s, analysis: d }));
        else if (payload.type === "openai_post_event") setState((s) => ({ ...s, openai_post_event: d }));
        else if (payload.type === "event_logged") setState((s) => ({ ...s, events: s.events.some((e) => e.episode_id === d.episode_id) ? s.events : [...s.events, d], lastEpisodeId: d.episode_id }));
        else if (payload.type === "status") setState((s) => ({ ...s, connections: { ...s.connections, esp32: d.esp32 === "CONNECTED" ? "CONNECTED" : "DISCONNECTED", runpod: d.runpod, grok: d.grok, lastMessageAt: Date.now() } }));
      };
    };
    connect();
    void loadReplayIndex().then((index) => setState((s) => ({ ...s, replay: { ...s.replay, index, loadError: !index } })));
    return () => { active = false; if (retry) clearTimeout(retry); socket?.close(); };
  }, []);

  const startDemo = useCallback(() => { samplesRef.current = []; setState((s) => ({ ...s, markers: [], events: s.events })); void command("/api/demo/start-walking"); }, []);
  const startMonitoring = useCallback(() => { void command("/api/monitoring/start"); }, []);
  const stopMonitoring = useCallback(() => { void command("/api/monitoring/stop"); }, []);
  const clearEvents = useCallback(() => { void command("/api/events", undefined, "DELETE"); }, []);
  const triggerFreeze = useCallback(() => { void command("/api/demo/simulate-freeze"); }, []);
  const reset = useCallback(() => { samplesRef.current = []; setLatest(null); setCadence(0); lastPhase.current = "IDLE"; setState((s) => ({ ...s, markers: [] })); void command("/api/demo/reset"); }, []);
  const armCue = useCallback((cue: { pattern: string; bpm: number }) => { void command("/api/cue", cue); }, []);
  const setSource = useCallback((source: SensorMode) => { samplesRef.current = []; setLatest(null); setCadence(0); setState((s) => ({ ...s, markers: [], replay: { ...s.replay, playing: false, finished: false } })); void command("/api/source", { source }); }, []);
  const selectReplay = useCallback((delta: number) => setState((s) => ({ ...s, replay: { ...s.replay, selected: (s.replay.selected + delta + (s.replay.index?.events.length ?? 1)) % (s.replay.index?.events.length ?? 1) } })), []);
  const replayLabeledEvent = useCallback(() => { const sample = stateRef.current.replay.index?.events[stateRef.current.replay.selected]; if (sample) { samplesRef.current = []; setState((s) => ({ ...s, markers: [], replay: { ...s.replay, playing: true, finished: false } })); void loadReplayEvent(sample.file).then((loaded) => setState((s) => ({ ...s, replay: { ...s.replay, loaded } }))); void command("/api/replay/start", { file: sample.file }); } }, []);
  return { state, monitoring, cadence, latest, samplesRef, startDemo, startMonitoring, stopMonitoring, triggerFreeze, clearEvents, reset, armCue, setSource, selectReplay, replayLabeledEvent };
}
