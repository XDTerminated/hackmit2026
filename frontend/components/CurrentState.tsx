"use client";

import { PHASE_CAPTION, PHASE_LABEL, STORY } from "@/lib/format";
import type { Phase } from "@/types";
import GaitFigure from "./GaitFigure";

export default function CurrentState({
  phase,
  storyStep,
  cadence,
  baseline,
  cueActive,
  cueBpm,
}: {
  phase: Phase;
  storyStep: number;
  cadence: number;
  baseline: number;
  cueActive: boolean;
  cueBpm: number;
}) {
  const label = PHASE_LABEL[phase];
  const long = label.length > 10;
  return (
    <section className="card card-accent relative flex h-full overflow-hidden">
      <div
        className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full opacity-30 blur-3xl"
        style={{ background: "var(--phase)" }}
      />
      <div className="relative flex min-w-0 flex-1 flex-col justify-between p-5">
        <div>
          <p className="label flex items-center gap-2">
            <span className="live-dot" />
            Current state
          </p>
          <h2
            key={phase}
            className={`phase-text value-display rise mt-2 font-bold leading-[0.95] ${
              long ? "text-[44px] xl:text-[56px]" : "text-[60px] xl:text-[76px]"
            }`}
          >
            {label}
          </h2>
          <p key={`${phase}-cap`} className="rise mt-3 max-w-[30ch] text-[14px] leading-snug text-white/65">
            {PHASE_CAPTION[phase]}
          </p>
        </div>

        <div className="relative mt-4">
          <div className="absolute left-[7px] right-[7px] top-[7px] h-px bg-white/12" />
          <div
            className="absolute left-[7px] top-[7px] h-px phase-bg transition-all duration-500"
            style={{ width: `calc(${(storyStep / (STORY.length - 1)) * 100}% - 14px)` }}
          />
          <ol className="relative grid grid-cols-5 gap-1">
            {STORY.map((step, i) => (
              <li key={step} className={`loop-node ${i < storyStep ? "done" : ""} ${i === storyStep ? "active" : ""}`}>
                <span className="dot" />
                <span className="text-[9.5px] tracking-[0.16em]">{step}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>

      <div className="relative flex w-[38%] shrink-0 items-end justify-center pb-2 pr-2 pt-6">
        <GaitFigure phase={phase} cadence={cadence} baseline={baseline} cueActive={cueActive} cueBpm={cueBpm} />
      </div>
    </section>
  );
}
