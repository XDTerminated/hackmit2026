/**
 * Service abstractions for RunPod verification and Grok analysis.
 *
 * Every call is time-boxed and falls back to a local mock, so demo mode
 * never blocks on — or errors because of — the backend, RunPod, or Grok.
 * Neither service can command the haptic motor; they only score/summarise.
 */

import type {
  Connections,
  CueParams,
  EventRecord,
  GrokAnalysis,
  RunPodResult,
} from "@/types";

// 127.0.0.1 avoids browsers preferring an IPv6 localhost route while the
// local FastAPI demo server is bound to IPv4.
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws/imu";

async function timeboxed<T>(path: string, init: RequestInit, ms: number): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------- health

export async function probeBackend(): Promise<{ reachable: boolean; connections: Partial<Connections> }> {
  const body = await timeboxed<{ connections?: { runpod?: string; grok?: string; esp32?: string } }>(
    "/",
    { method: "GET" },
    1200,
  );
  if (!body) return { reachable: false, connections: {} };
  const c = body.connections || {};
  return {
    reachable: true,
    connections: {
      runpod: c.runpod === "ONLINE" ? "ONLINE" : "MOCK",
      grok: c.grok === "ONLINE" ? "ONLINE" : "MOCK",
    },
  };
}

// ---------------------------------------------------------------- RunPod

export function mockRunPod(hint: "freeze_like" | "walking"): RunPodResult {
  return hint === "freeze_like"
    ? { classification: "freeze_like", confidence: 0.88 + Math.random() * 0.06, model_version: "mock-imu-v0", status: "mock" }
    : { classification: "walking", confidence: 0.12 + Math.random() * 0.08, model_version: "mock-imu-v0", status: "mock" };
}

export async function verifyWithRunPod(
  features: Record<string, unknown>,
  hint: "freeze_like" | "walking",
  budgetMs = 600,
): Promise<RunPodResult> {
  const body = await timeboxed<RunPodResult>(
    "/api/runpod/inference",
    { method: "POST", body: JSON.stringify({ ...features, hint }) },
    budgetMs,
  );
  if (body && typeof body.confidence === "number" && body.classification) {
    return {
      classification: body.classification,
      confidence: Math.max(0, Math.min(1, body.confidence)),
      model_version: body.model_version || "runpod",
      status: body.status === "complete" ? "complete" : "mock",
    };
  }
  return mockRunPod(hint);
}

// ---------------------------------------------------------------- Grok

export async function analyzeWithGrok(
  events: EventRecord[],
  allowed: CueParams[],
  baseline: number,
  budgetMs = 900,
): Promise<GrokAnalysis> {
  const body = await timeboxed<GrokAnalysis>("/api/grok/analyze", { method: "POST" }, budgetMs);
  // Only trust a live (non-mock) Grok answer that respects allowed cues; otherwise
  // compute the evidence-first summary locally from the demo's own event log.
  if (body && body.mock === false && body.next_experiment) {
    const ok =
      !body.recommended_cue ||
      allowed.some((c) => c.bpm === body.recommended_cue!.bpm && c.pattern === body.recommended_cue!.pattern);
    if (ok) return body;
  }
  return mockGrok(events, allowed, baseline);
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function mockGrok(events: EventRecord[], allowed: CueParams[], baseline: number): GrokAnalysis {
  const n = events.length;
  const byBpm = new Map<number, number[]>();
  for (const e of events) {
    if (e.recovery.detected && e.recovery.time_ms != null) {
      byBpm.set(e.cue.bpm, [...(byBpm.get(e.cue.bpm) || []), e.recovery.time_ms]);
    }
  }
  const medians = [...byBpm.entries()].map(([bpm, times]) => ({ bpm, med: median(times), n: times.length }));
  medians.sort((a, b) => a.med - b.med);
  const best = medians[0];
  // Prefer comparing against the tempo closest to baseline cadence first.
  const unused = allowed
    .filter((c) => !byBpm.has(c.bpm))
    .sort((a, b) => Math.abs(a.bpm - baseline) - Math.abs(b.bpm - baseline));
  const leastSampled = [...allowed].sort((a, b) => (byBpm.get(a.bpm)?.length || 0) - (byBpm.get(b.bpm)?.length || 0))[0];

  let observation: string;
  let evidence: string;
  let next: string;
  if (!best) {
    observation = "No freeze-like episodes logged yet.";
    evidence = "0 observations";
    next = `Collect a first observation at ${allowed[1]?.bpm ?? 95} BPM.`;
  } else if (best.n === 1 && medians.length === 1) {
    observation = `${best.bpm} BPM recovered in ${(best.med / 1000).toFixed(2)} s in a single observation.`;
    evidence = "1 observation";
    next = unused.length
      ? `Compare ${best.bpm} BPM vs ${unused[0].bpm} BPM.`
      : `Collect more observations at ${leastSampled.bpm} BPM.`;
  } else {
    observation = `${best.bpm} BPM currently has the shortest observed recovery (${(best.med / 1000).toFixed(2)} s median).`;
    evidence = `${best.n} observation${best.n === 1 ? "" : "s"}`;
    next = unused.length
      ? `Compare ${best.bpm} BPM vs ${unused[0].bpm} BPM.`
      : `Collect more observations across ${allowed.map((c) => c.bpm).join(" / ")} BPM before ranking.`;
  }
  const confidence =
    n >= 8 && medians.length >= 2
      ? "Early trend only — an observation, not a clinical finding."
      : "More observations required.";

  const recommended: CueParams | null = unused[0] ?? leastSampled ?? null;

  const comparison = allowed
    .map((c) => {
      const t = byBpm.get(c.bpm);
      return t ? `- ${c.pattern} ${c.bpm} BPM: n=${t.length}, median recovery ${(median(t) / 1000).toFixed(2)} s` : `- ${c.pattern} ${c.bpm} BPM: n=0`;
    })
    .join("\n");
  const sessionSummary = `${n} possible freeze-like episode${n === 1 ? "" : "s"} against a ${baseline.toFixed(0)} BPM baseline. Cues were dispatched by the local/edge loop; cloud models only scored or summarised afterwards.`;
  const observations = `${observation} Edge and RunPod confidences are research scores for freeze-like gait patterns — not a clinical confirmation of FoG.`;
  const safety = "Grok and RunPod never command the vibration motor. Cue timing stays on-device / edge-local. Next cues may only be chosen from allowed_next_cues.";
  const limitation = "Small-n prototype with simulated IMU in demo mode. Findings are hypotheses for the next walking trial, not treatment recommendations.";

  return {
    summary: `${n} event${n === 1 ? "" : "s"} analyzed.`,
    observation,
    evidence,
    next_experiment: next,
    confidence_statement: confidence,
    session_summary: sessionSummary,
    cue_comparison: comparison,
    observations,
    safety,
    limitation,
    full_analysis: [
      "## SESSION SUMMARY",
      sessionSummary,
      "## CUE COMPARISON",
      comparison,
      "## OBSERVATIONS",
      observations,
      "## NEXT EXPERIMENT",
      next,
      "## SAFETY",
      safety,
      "## LIMITATION",
      limitation,
    ].join("\n\n"),
    recommended_cue: recommended,
    mock: true,
  };
}

// ---------------------------------------------------------------- mirroring (fire-and-forget)

export function mirrorEvent(event: EventRecord): void {
  void timeboxed("/api/event", { method: "POST", body: JSON.stringify(event) }, 1500);
}

export function mirrorReset(): void {
  void timeboxed("/api/demo/reset", { method: "POST" }, 1500);
}
