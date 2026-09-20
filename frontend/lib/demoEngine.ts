"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { DemoSimulatorSource } from "./datasources/demoSimulatorSource";
import { ESP32StreamSource, type StreamStatus } from "./datasources/esp32StreamSource";
import { ReplayDatasetSource, loadReplayEvent, loadReplayIndex } from "./datasources/replayDatasetSource";
import type { DataSource, ReplayEvent, SignalMarker } from "./datasources/types";
import { WS_URL, analyzeWithGrok, mirrorEvent, mirrorReset, probeBackend, verifyWithRunPod } from "./services";
import type {
  CueParams,
  DemoState,
  EventRecord,
  GrokAnalysis,
  IMUSample,
  Phase,
  RunPodResult,
  SensorMode,
} from "@/types";

// ------------------------------------------------------------------ state

const ALLOWED: CueParams[] = [
  { pattern: "rhythmic", bpm: 80 },
  { pattern: "rhythmic", bpm: 95 },
  { pattern: "rhythmic", bpm: 102 },
];

const BASELINE = 102;

function initialState(): DemoState {
  return {
    source: "DEMO",
    phase: "IDLE",
    running: false,
    storyStep: 0,
    baseline_cadence_bpm: BASELINE,
    allowed_next_cues: ALLOWED,
    edge: { classification: "walking", confidence: 0.06, latency_ms: 18 },
    runpod: { classification: "unknown", confidence: 0, model_version: "mock-imu-v0", status: "idle" },
    cue: { pattern: "rhythmic", bpm: 95, active: false, source: "edge_local" },
    recovery: { detected: false, elapsed_ms: 0, time_ms: null, pre_cadence: BASELINE, post_cadence: null },
    analysis: null,
    openai_post_event: null,
    events: [],
    lastEpisodeId: null,
    markers: [],
    replay: { index: null, selected: 0, loaded: null, playing: false, finished: false, loadError: false },
    connections: {
      esp32: "DISCONNECTED",
      socket: "closed",
      socketAttempts: 0,
      lastMessageAt: null,
      runpod: "MOCK",
      grok: "MOCK",
      backendReachable: false,
    },
  };
}

type Action =
  | { type: "START"; baseline?: number }
  | { type: "RESET" }
  | { type: "SOURCE"; source: SensorMode }
  | { type: "SEQUENCE_START" }
  | { type: "RUNNING" }
  | { type: "PHASE"; phase: Phase; storyStep?: number }
  | { type: "EDGE"; confidence: number }
  | { type: "RUNPOD"; runpod: RunPodResult }
  | { type: "CUE_ACTIVE"; active: boolean }
  | { type: "MARKER"; marker: SignalMarker }
  | { type: "RECOVERY_TICK"; elapsed_ms: number }
  | { type: "RECOVERED"; event: EventRecord }
  | { type: "ANALYSIS"; analysis: GrokAnalysis }
  | { type: "SEQUENCE_DONE" }
  | { type: "ARM"; cue: CueParams }
  | { type: "REPLAY"; patch: Partial<DemoState["replay"]> }
  | { type: "CONNECTIONS"; patch: Partial<DemoState["connections"]> };

function reducer(s: DemoState, a: Action): DemoState {
  switch (a.type) {
    case "START": {
      const fresh = initialState();
      return {
        ...fresh,
        source: s.source,
        phase: "WALKING",
        baseline_cadence_bpm: a.baseline ?? BASELINE,
        recovery: { ...fresh.recovery, pre_cadence: a.baseline ?? BASELINE },
        connections: s.connections,
        replay: { ...s.replay, playing: false, finished: false },
        cue: { ...fresh.cue, bpm: s.cue.bpm },
      };
    }
    case "RESET":
      return {
        ...initialState(),
        source: s.source,
        connections: s.connections,
        replay: { ...s.replay, loaded: s.replay.loaded, playing: false, finished: false },
      };
    case "SOURCE":
      return {
        ...initialState(),
        source: a.source,
        connections: s.connections,
        replay: { ...s.replay, playing: false, finished: false },
        cue: { ...initialState().cue, bpm: s.cue.bpm },
      };
    case "SEQUENCE_START": {
      const fresh = initialState();
      return {
        ...s,
        running: true,
        phase: "POSSIBLE_FREEZE",
        storyStep: 1,
        analysis: null,
        markers: [],
        runpod: fresh.runpod,
        recovery: { ...fresh.recovery, pre_cadence: s.baseline_cadence_bpm },
        cue: { ...s.cue, active: false },
      };
    }
    case "RUNNING":
      return { ...s, running: true };
    case "PHASE":
      return { ...s, phase: a.phase, storyStep: a.storyStep ?? s.storyStep };
    case "EDGE":
      return {
        ...s,
        edge: {
          ...s.edge,
          confidence: a.confidence,
          classification: a.confidence >= 0.6 ? "freeze_like" : a.confidence >= 0.3 ? "unknown" : "walking",
        },
      };
    case "RUNPOD":
      return { ...s, runpod: a.runpod };
    case "CUE_ACTIVE":
      return { ...s, cue: { ...s.cue, active: a.active } };
    case "MARKER":
      return { ...s, markers: [...s.markers, a.marker] };
    case "RECOVERY_TICK":
      return { ...s, recovery: { ...s.recovery, elapsed_ms: a.elapsed_ms } };
    case "RECOVERED":
      return {
        ...s,
        phase: "RECOVERED",
        storyStep: 3,
        cue: { ...s.cue, active: false },
        recovery: {
          detected: true,
          elapsed_ms: a.event.recovery.time_ms ?? s.recovery.elapsed_ms,
          time_ms: a.event.recovery.time_ms,
          pre_cadence: a.event.pre_cadence ?? s.baseline_cadence_bpm,
          post_cadence: a.event.post_cadence,
        },
        events: [...s.events, a.event],
        lastEpisodeId: a.event.episode_id,
      };
    case "ANALYSIS":
      return { ...s, analysis: a.analysis };
    case "SEQUENCE_DONE":
      return { ...s, phase: "OUTCOME", storyStep: 4, running: false };
    case "ARM":
      return { ...s, cue: { ...s.cue, bpm: a.cue.bpm, pattern: a.cue.pattern } };
    case "REPLAY":
      return { ...s, replay: { ...s.replay, ...a.patch } };
    case "CONNECTIONS":
      return { ...s, connections: { ...s.connections, ...a.patch } };
  }
}

// ------------------------------------------------------------------ engine

export function useDemoEngine() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const [cadence, setCadence] = useState(0);
  const [latest, setLatest] = useState<IMUSample | null>(null);

  const samplesRef = useRef<IMUSample[]>([]);
  const demoRef = useRef<DemoSimulatorSource | null>(null);
  if (!demoRef.current) demoRef.current = new DemoSimulatorSource(BASELINE);
  const liveRef = useRef<ESP32StreamSource | null>(null);
  const activeRef = useRef<DataSource | null>(null);

  const timers = useRef<number[]>([]);
  const recoveryTimer = useRef<number | null>(null);
  const runId = useRef(0);
  const runningRef = useRef(false);
  const episodeCount = useRef(0);
  const replayCount = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  // ---- common sink: every DataSource pushes here
  const lastUiAt = useRef(0);
  const sink = useCallback((s: IMUSample) => {
    const buf = samplesRef.current;
    buf.push(s);
    if (buf.length > 1200) buf.splice(0, buf.length - 1200);
    const now = performance.now();
    if (now - lastUiAt.current > 250) {
      lastUiAt.current = now;
      setLatest(s);
      const src = activeRef.current;
      if (src instanceof DemoSimulatorSource) setCadence(src.cadence);
      else if (s.cadence_bpm != null) setCadence(s.cadence_bpm);
      else setCadence(estimateCadence(buf));
    }
  }, []);

  const switchSource = useCallback(
    (src: DataSource | null) => {
      activeRef.current?.stop();
      activeRef.current = src;
      src?.start(sink);
    },
    [sink],
  );

  const lastTs = () => samplesRef.current.at(-1)?.timestamp ?? 0;

  // ---- boot: demo simulator idle, probe backend, preload replay index
  useEffect(() => {
    switchSource(demoRef.current);
    probeBackend().then((r) => dispatch({ type: "CONNECTIONS", patch: { backendReachable: r.reachable, ...r.connections } }));
    loadReplayIndex().then((index) => dispatch({ type: "REPLAY", patch: { index, loadError: !index } }));
    return () => {
      activeRef.current?.stop();
      liveRef.current?.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- scheduling helpers
  const cancelSequence = useCallback(() => {
    runId.current += 1;
    runningRef.current = false;
    for (const t of timers.current) window.clearTimeout(t);
    timers.current = [];
    if (recoveryTimer.current != null) {
      window.clearInterval(recoveryTimer.current);
      recoveryTimer.current = null;
    }
  }, []);

  useEffect(() => cancelSequence, [cancelSequence]);

  const clearSignal = () => {
    samplesRef.current = [];
    setLatest(null);
  };

  // ---- controls -------------------------------------------------------
  const startDemo = useCallback(() => {
    cancelSequence();
    const demo = demoRef.current!;
    demo.reset(BASELINE);
    demo.setGaitMode("walking");
    clearSignal();
    switchSource(demo);
    dispatch({ type: "START" });
  }, [cancelSequence, switchSource]);

  const reset = useCallback(() => {
    cancelSequence();
    const src = stateRef.current.source;
    const demo = demoRef.current!;
    demo.reset(BASELINE);
    demo.setGaitMode("idle");
    clearSignal();
    episodeCount.current = 0;
    replayCount.current = 0;
    setCadence(0);
    if (src === "LIVE") switchSource(liveRef.current);
    else switchSource(demo);
    dispatch({ type: "RESET" });
    mirrorReset();
  }, [cancelSequence, switchSource]);

  const setSource = useCallback(
    (source: SensorMode) => {
      if (stateRef.current.source === source) return;
      cancelSequence();
      clearSignal();
      episodeCount.current = 0;
      replayCount.current = 0;
      setCadence(0);
      const demo = demoRef.current!;
      demo.reset(BASELINE);
      demo.setGaitMode("idle");
      if (source === "LIVE") {
        if (!liveRef.current) {
          liveRef.current = new ESP32StreamSource(WS_URL, (st: StreamStatus) =>
            dispatch({
              type: "CONNECTIONS",
              patch: {
                esp32: st.device ? "CONNECTED" : "DISCONNECTED",
                socket: st.socket,
                socketAttempts: st.attempts,
                lastMessageAt: st.lastMessageAt,
                runpod: st.runpod,
                grok: st.grok,
              },
            }),
          );
        }
        switchSource(liveRef.current);
      } else {
        liveRef.current?.stop();
        switchSource(demo);
      }
      dispatch({ type: "SOURCE", source });
    },
    [cancelSequence, switchSource],
  );

  // shared tail: verification result shown → analysis → outcome
  const finishEpisode = useCallback(
    async (id: number, event: EventRecord, until: (ms: number) => Promise<void>, atMs: number) => {
      const alive = () => runId.current === id;
      // hold RECOVERED long enough for "RECOVERY DETECTED · 1.42 s" to land
      await until(atMs + 1200);
      if (!alive()) return;
      dispatch({ type: "PHASE", phase: "ANALYZING", storyStep: 4 });
      const events = [...stateRef.current.events];
      if (!events.some((e) => e.episode_id === event.episode_id)) events.push(event);
      const analysisP = analyzeWithGrok(events, ALLOWED, stateRef.current.baseline_cadence_bpm, 800);
      await until(atMs + 2200);
      if (!alive()) return;
      const analysis = await analysisP;
      if (!alive()) return;
      dispatch({ type: "ANALYSIS", analysis });
      dispatch({ type: "SEQUENCE_DONE" });
      runningRef.current = false;
    },
    [],
  );

  const triggerFreeze = useCallback(() => {
    if (runningRef.current) return;
    if (stateRef.current.source !== "DEMO") return;
    if (stateRef.current.phase === "IDLE") startDemo();

    const id = ++runId.current;
    runningRef.current = true;
    const demo = demoRef.current!;
    const t0 = performance.now();
    const alive = () => runId.current === id;
    const until = (ms: number) =>
      new Promise<void>((resolve) => {
        const delay = Math.max(0, t0 + ms - performance.now());
        timers.current.push(window.setTimeout(resolve, delay));
      });

    const run = async () => {
      // 0 ms — freeze-like pattern; edge score ramps quickly
      dispatch({ type: "SEQUENCE_START" });
      demo.setGaitMode("freeze");
      const edgeTarget = 0.82 + Math.random() * 0.06;
      const ramp = [0.42, 0.58, 0.71, 0.78, edgeTarget];
      for (let i = 0; i < ramp.length; i++) {
        await until(i * 90);
        if (!alive()) return;
        dispatch({ type: "EDGE", confidence: ramp[i] });
      }

      // 500 ms — detected; RunPod verification requested (time-boxed)
      await until(500);
      if (!alive()) return;
      dispatch({ type: "PHASE", phase: "DETECTED", storyStep: 1 });
      dispatch({ type: "MARKER", marker: { t_ms: lastTs(), kind: "DETECTION" } });
      dispatch({ type: "RUNPOD", runpod: { classification: "unknown", confidence: 0, model_version: "…", status: "pending" } });
      const verification = verifyWithRunPod({ accel_variance: 0.12, window: "demo-freeze-like" }, "freeze_like", 450);

      // 1000 ms — cue fires from the EDGE score; RunPod result shown alongside
      await until(1000);
      if (!alive()) return;
      const rp = await verification;
      if (!alive()) return;
      dispatch({ type: "RUNPOD", runpod: rp });
      dispatch({ type: "PHASE", phase: "CUE_TRIGGERED", storyStep: 2 });
      dispatch({ type: "CUE_ACTIVE", active: true });
      dispatch({ type: "MARKER", marker: { t_ms: lastTs(), kind: "CUE" } });

      // 2000 ms — recovery monitoring
      await until(2000);
      if (!alive()) return;
      dispatch({ type: "PHASE", phase: "RECOVERY_MONITORING", storyStep: 3 });
      const recStart = performance.now();
      recoveryTimer.current = window.setInterval(() => {
        if (!alive()) return;
        dispatch({ type: "RECOVERY_TICK", elapsed_ms: Math.round(performance.now() - recStart) });
      }, 50);

      // gait regularity starts returning ~0.9 s before RECOVERED (gradual, not a jump)
      const recoverAt = 3400 + Math.random() * 400; // → 1.4–1.8 s recovery
      await until(recoverAt - 900);
      if (!alive()) return;
      demo.setGaitMode("recovering");

      await until(recoverAt);
      if (!alive()) return;
      if (recoveryTimer.current != null) {
        window.clearInterval(recoveryTimer.current);
        recoveryTimer.current = null;
      }
      const recoveryMs = Math.round(performance.now() - recStart);
      const cur = stateRef.current;
      episodeCount.current += 1;
      const event: EventRecord = {
        episode_id: `E${String(episodeCount.current).padStart(2, "0")}`,
        timestamp_iso: new Date().toISOString(),
        edge: { classification: "freeze_like", confidence: cur.edge.confidence },
        runpod: rp,
        cue: { ...cur.cue, active: false },
        recovery: { detected: true, time_ms: recoveryMs },
        status: "Recovered",
        event_duration_ms: Math.round(recoverAt),
        pre_cadence: BASELINE,
        post_cadence: Math.round(BASELINE - 1 - Math.random() * 2),
      };
      dispatch({ type: "RECOVERED", event });
      dispatch({ type: "MARKER", marker: { t_ms: lastTs(), kind: "RECOVERY" } });
      mirrorEvent(event);

      await finishEpisode(id, event, until, recoverAt);
    };

    void run().catch(() => {
      if (!alive()) return;
      demo.setGaitMode("walking");
      dispatch({ type: "SEQUENCE_DONE" });
      runningRef.current = false;
    });
  }, [startDemo, finishEpisode]);

  // ---- replay -----------------------------------------------------------
  const selectReplay = useCallback((delta: number) => {
    const r = stateRef.current.replay;
    const n = r.index?.events.length ?? 0;
    if (!n) return;
    dispatch({ type: "REPLAY", patch: { selected: (r.selected + delta + n) % n, finished: false } });
  }, []);

  const replayLabeledEvent = useCallback(async () => {
    if (runningRef.current) return;
    const r = stateRef.current.replay;
    const meta = r.index?.events[r.selected];
    if (!meta) return;
    cancelSequence();
    const id = ++runId.current;
    runningRef.current = true;
    const alive = () => runId.current === id;

    let ev: ReplayEvent | null = r.loaded && r.loaded.event_id === meta.event_id ? r.loaded : null;
    if (!ev) ev = await loadReplayEvent(meta.file);
    if (!alive()) return;
    if (!ev) {
      dispatch({ type: "REPLAY", patch: { loadError: true } });
      runningRef.current = false;
      return;
    }
    const event = ev;

    clearSignal();
    replayCount.current += 1;
    dispatch({ type: "START", baseline: event.baseline_cadence_bpm });
    dispatch({ type: "REPLAY", patch: { loaded: event, playing: true, finished: false, loadError: false } });
    dispatch({ type: "RUNNING" });

    const { detection_t, cue_t, recovery_t } = event.markers;
    const edgeTarget = 0.8 + Math.random() * 0.08;
    let step = 0;
    let rp: RunPodResult | null = null;
    let verification: Promise<RunPodResult> | null = null;
    let episode: EventRecord | null = null;
    const t0 = performance.now();
    const until = (ms: number) =>
      new Promise<void>((resolve) => {
        const delay = Math.max(0, t0 + ms - performance.now());
        timers.current.push(window.setTimeout(resolve, delay));
      });

    const onTick = (t: number) => {
      if (!alive()) return;
      // step 0: pre-detection hesitation → POSSIBLE_FREEZE with edge ramp
      if (step === 0 && t >= detection_t - 0.6) {
        step = 1;
        dispatch({ type: "PHASE", phase: "POSSIBLE_FREEZE", storyStep: 1 });
      }
      if (step === 1) {
        const k = Math.min(1, (t - (detection_t - 0.6)) / 0.6);
        dispatch({ type: "EDGE", confidence: 0.08 + (edgeTarget - 0.08) * k });
        if (t >= detection_t) {
          step = 2;
          dispatch({ type: "PHASE", phase: "DETECTED", storyStep: 1 });
          dispatch({ type: "MARKER", marker: { t_ms: Math.round(detection_t * 1000), kind: "DETECTION" } });
          dispatch({ type: "RUNPOD", runpod: { classification: "unknown", confidence: 0, model_version: "…", status: "pending" } });
          verification = verifyWithRunPod({ source: "FoG-STAR", event_id: event.event_id }, "freeze_like", 450);
          verification.then((res) => {
            if (alive()) rp = res;
          });
        }
      }
      if (step === 2 && t >= cue_t) {
        step = 3;
        if (rp) dispatch({ type: "RUNPOD", runpod: rp });
        else verification?.then((res) => alive() && dispatch({ type: "RUNPOD", runpod: res }));
        dispatch({ type: "PHASE", phase: "CUE_TRIGGERED", storyStep: 2 });
        dispatch({ type: "CUE_ACTIVE", active: true });
        dispatch({ type: "MARKER", marker: { t_ms: Math.round(cue_t * 1000), kind: "CUE" } });
      }
      if (step === 3 && t >= cue_t + 0.4) {
        step = 4;
        dispatch({ type: "PHASE", phase: "RECOVERY_MONITORING", storyStep: 3 });
      }
      if (step === 4) {
        dispatch({ type: "RECOVERY_TICK", elapsed_ms: Math.round((t - cue_t) * 1000) });
        if (t >= recovery_t) {
          step = 5;
          const recoveryMs = Math.round((recovery_t - cue_t) * 1000);
          const cur = stateRef.current;
          episode = {
            episode_id: `R${String(replayCount.current).padStart(2, "0")}`,
            timestamp_iso: new Date().toISOString(),
            edge: { classification: "freeze_like", confidence: cur.edge.confidence },
            runpod: rp ?? cur.runpod,
            cue: { ...cur.cue, active: false },
            recovery: { detected: true, time_ms: recoveryMs },
            status: `Recovered · ${event.source} ${event.event_id}`,
            event_duration_ms: Math.round(((event.fog_offset_t ?? recovery_t) - (event.fog_onset_t ?? detection_t)) * 1000),
            pre_cadence: event.baseline_cadence_bpm,
            post_cadence: null,
          };
          dispatch({ type: "RECOVERED", event: episode });
          dispatch({ type: "MARKER", marker: { t_ms: Math.round(recovery_t * 1000), kind: "RECOVERY" } });
          mirrorEvent(episode);
          void finishEpisode(id, episode, until, performance.now() - t0);
        }
      }
    };

    const onEnd = () => {
      if (!alive()) return;
      dispatch({ type: "REPLAY", patch: { playing: false, finished: true } });
      if (step < 5) {
        // window ended before the labelled offset — close out gracefully
        runningRef.current = false;
        dispatch({ type: "SEQUENCE_DONE" });
      }
    };

    switchSource(new ReplayDatasetSource(event, onTick, onEnd));
  }, [cancelSequence, switchSource, finishEpisode]);

  const armCue = useCallback((cue: CueParams) => {
    if (!ALLOWED.some((c) => c.bpm === cue.bpm && c.pattern === cue.pattern)) return;
    dispatch({ type: "ARM", cue });
  }, []);

  return {
    state,
    cadence,
    latest,
    samplesRef,
    startDemo,
    triggerFreeze,
    reset,
    armCue,
    setSource,
    selectReplay,
    replayLabeledEvent,
  };
}

/** Cadence from acc-magnitude peaks over the last ~4 s (used for replay / live streams). */
function estimateCadence(buf: IMUSample[]): number {
  const n = buf.length;
  if (n < 40) return 0;
  const tEnd = buf[n - 1].timestamp;
  let i0 = n - 1;
  while (i0 > 0 && tEnd - buf[i0 - 1].timestamp <= 4000) i0--;
  const win = buf.slice(i0);
  if (win.length < 20) return 0;
  const mean = win.reduce((a, s) => a + s.accel_mag, 0) / win.length;
  const sd = Math.sqrt(win.reduce((a, s) => a + (s.accel_mag - mean) ** 2, 0) / win.length) || 1e-6;
  const thr = mean + 0.7 * sd;
  const peaks: number[] = [];
  for (let i = 1; i < win.length - 1; i++) {
    const s = win[i];
    if (s.accel_mag > thr && s.accel_mag >= win[i - 1].accel_mag && s.accel_mag >= win[i + 1].accel_mag) {
      if (!peaks.length || s.timestamp - peaks[peaks.length - 1] >= 380) peaks.push(s.timestamp);
    }
  }
  if (peaks.length < 3) return 0;
  return (60000 * (peaks.length - 1)) / (peaks[peaks.length - 1] - peaks[0]);
}
