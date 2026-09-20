"use client";

import { useState } from "react";
import { seconds } from "@/lib/format";
import type { CueInfo, CueParams, GrokAnalysis, Phase, RecoveryInfo } from "@/types";
import AnalysisModal from "./AnalysisModal";

export default function OutcomePanel({
  analysis,
  phase,
  cue,
  recovery,
  onArm,
}: {
  analysis: GrokAnalysis | null;
  phase: Phase;
  cue: CueInfo;
  recovery: RecoveryInfo;
  onArm: (cue: CueParams) => void;
}) {
  const [open, setOpen] = useState(false);
  const analyzing = phase === "ANALYZING";

  if (!analysis && !analyzing) {
    return (
      <section className="card flex h-full flex-col justify-center gap-1 px-5 py-4">
        <p className="label">Outcome · adaptive analysis</p>
        <p className="text-[14px] text-white/55">Appears after the first episode. Each recovery time is logged and used to choose the next cue experiment.</p>
      </section>
    );
  }

  return (
    <section className={`card flex h-full flex-col p-4 ${phase === "OUTCOME" ? "card-accent" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="label">Adaptive analysis</p>
          <h3 className="value-display text-xl font-semibold text-white">OUTCOME LEARNED</h3>
        </div>
        <span className="rounded-full bg-white/5 px-3 py-1 font-mono text-[9.5px] uppercase tracking-[0.18em] text-white/45">
          {analyzing && !analysis ? "analysing…" : `reasoning: Grok${analysis?.mock ? " · mock" : ""}`}
        </span>
      </div>

      {analyzing && !analysis ? (
        <div className="mt-4 flex flex-1 items-center gap-3 text-white/60">
          <span className="live-dot" />
          <p className="text-[14px]">Comparing this recovery with previous episodes…</p>
        </div>
      ) : analysis ? (
        <div key={analysis.observation + analysis.evidence} className="rise mt-2 flex flex-1 flex-col gap-2">
          <Row label="Observed" text={analysis.observation} />
          <div className="grid grid-cols-2 gap-3">
            <Row label="Recovery" text={recovery.time_ms != null ? seconds(recovery.time_ms) : "—"} big />
            <Row label="Evidence" text={analysis.evidence} big />
          </div>
          <div className="rounded-xl border p-3" style={{ background: "rgb(var(--phase-rgb) / 0.08)", borderColor: "rgb(var(--phase-rgb) / 0.4)" }}>
            <p className="label">Next experiment</p>
            <p className="mt-0.5 text-[16px] font-medium leading-snug text-white">{analysis.next_experiment}</p>
          </div>
          <Row label="Confidence" text={analysis.confidence_statement} />

          <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="rounded-lg border border-white/15 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-white hover:border-white/40"
            >
              View full analysis
            </button>
            {analysis.recommended_cue && analysis.recommended_cue.bpm !== cue.bpm ? (
              <button
                type="button"
                onClick={() => onArm(analysis.recommended_cue!)}
                className="rounded-lg px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-black phase-bg"
              >
                Arm {analysis.recommended_cue.bpm} BPM for next trial
              </button>
            ) : (
              <span className="font-mono text-[9.5px] uppercase tracking-[0.18em] text-white/40">next cue armed locally · {cue.bpm} BPM</span>
            )}
          </div>
        </div>
      ) : null}

      {open && analysis && <AnalysisModal analysis={analysis} onClose={() => setOpen(false)} />}
    </section>
  );
}

function Row({ label, text, big }: { label: string; text: string; big?: boolean }) {
  return (
    <div>
      <p className="label">{label}</p>
      <p className={`${big ? "value-display text-[22px] font-semibold text-white" : "text-[14px] leading-snug text-white/80"} mt-0.5`}>{text}</p>
    </div>
  );
}
