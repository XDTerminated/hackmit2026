"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { GrokAnalysis } from "@/types";

export default function AnalysisModal({
  analysis,
  onClose,
}: {
  analysis: GrokAnalysis;
  onClose: () => void;
}) {
  const sections = [
    { title: "SESSION SUMMARY", body: analysis.session_summary },
    { title: "CUE COMPARISON", body: analysis.cue_comparison },
    { title: "OBSERVATIONS", body: analysis.observations },
    { title: "NEXT EXPERIMENT", body: analysis.next_experiment },
    { title: "SAFETY", body: analysis.safety },
    { title: "LIMITATION", body: analysis.limitation },
  ];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const node = (
    <div className="modal-scrim fixed inset-0 z-[80] flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="card card-accent rise max-h-[86vh] w-full max-w-3xl overflow-y-auto bg-[#0a0e16] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="label">Grok · observational only</p>
            <h3 className="value-display text-3xl font-semibold text-white">FULL ANALYSIS</h3>
            <p className="mt-1 text-sm text-white/50">{analysis.summary}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/15 px-2 py-1 font-mono text-xs text-white/70"
          >
            CLOSE
          </button>
        </div>
        <div className="space-y-5">
          {sections.map((s) => (
            <section key={s.title}>
              <h4 className="value-display text-lg tracking-[0.14em] text-white">{s.title}</h4>
              <pre className="mt-1 whitespace-pre-wrap font-sans text-sm leading-relaxed text-white/70">
                {s.body || "—"}
              </pre>
            </section>
          ))}
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return null;
  return createPortal(node, document.body);
}
