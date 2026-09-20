"use client";

import { useEffect, useRef } from "react";
import type { Phase } from "@/types";

type FigureMode = "stand" | "walk" | "freeze" | "recover";

function modeFor(phase: Phase): FigureMode {
  switch (phase) {
    case "IDLE":
      return "stand";
    case "POSSIBLE_FREEZE":
    case "DETECTED":
    case "CUE_TRIGGERED":
      return "freeze";
    case "RECOVERY_MONITORING":
      return "recover";
    default:
      return "walk";
  }
}

const HIP = { x: 112, y: 132 };
const THIGH = 70;
const SHIN = 66;

/**
 * Semi-realistic lower-body gait silhouette (sagittal view).
 * Joint angles follow a simplified gait cycle; amplitude collapses during
 * freeze-like phases (hesitant micro-motion + trembling around the shank) and
 * ramps back during recovery. The ankle wearable emits BPM-timed pulse rings
 * while a cue is active.
 */
export default function GaitFigure({
  phase,
  cadence,
  baseline,
  cueActive,
  cueBpm,
}: {
  phase: Phase;
  cadence: number;
  baseline: number;
  cueActive: boolean;
  cueBpm: number;
}) {
  const refs = {
    pelvis: useRef<SVGGElement>(null),
    torso: useRef<SVGGElement>(null),
    nHip: useRef<SVGGElement>(null),
    nKnee: useRef<SVGGElement>(null),
    nAnkle: useRef<SVGGElement>(null),
    fHip: useRef<SVGGElement>(null),
    fKnee: useRef<SVGGElement>(null),
    fAnkle: useRef<SVGGElement>(null),
    glow: useRef<SVGEllipseElement>(null),
  };
  const modeRef = useRef<FigureMode>(modeFor(phase));
  modeRef.current = modeFor(phase);
  const cadenceRef = useRef(cadence);
  cadenceRef.current = cadence;
  const baselineRef = useRef(baseline);
  baselineRef.current = baseline;

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = performance.now();
    let phi = 0;
    let amp = 0;
    let tremEnv = 0;
    let tremTarget = 0;
    let tremSwitch = 0;
    let lean = 0;

    const set = (el: SVGElement | null, v: string) => el?.setAttribute("transform", v);

    const legAngles = (p: number, a: number, tremor: number) => {
      const hip = a * 17 * Math.cos(p) + 2 + tremor * 0.4;
      const swing = Math.exp(-0.5 * ((wrap(p - 4.35) / 0.62) ** 2));
      const knee = 4 + a * (8 * (0.5 + 0.5 * Math.cos(2 * p - 0.5)) + 46 * swing) + tremor;
      const foot = -a * 6 * Math.sin(p - 0.4);
      return { hip, knee, foot };
    };

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const mode = modeRef.current;

      // amplitude envelope per mode
      const target = mode === "stand" ? 0 : mode === "freeze" ? 0.14 : 1;
      const rate = mode === "recover" ? 0.6 : mode === "freeze" ? 4 : 2.2;
      amp += (target - amp) * Math.min(1, dt * rate);

      // The sensor cadence is a real readout; the figure uses a slower visual
      // cadence so a 102 BPM step signal still reads as calm walking, not running.
      const measured = Math.max(cadenceRef.current, 0.4 * baselineRef.current);
      const visualCadence = mode === "freeze" ? 0.34 * baselineRef.current : measured * 0.72;
      phi += Math.PI * (visualCadence / 60) * dt * (mode === "stand" ? 0 : 1);

      // trembling bursts around the shank during freeze-like phases
      if (mode === "freeze") {
        if (t > tremSwitch) {
          tremTarget = Math.random() < 0.35 ? 0 : 0.6 + Math.random() * 0.4;
          tremSwitch = t + 0.25 + Math.random() * 0.5;
        }
      } else tremTarget = 0;
      tremEnv += (tremTarget - tremEnv) * Math.min(1, dt * 8);
      const tremor = tremEnv * 3.2 * Math.sin(2 * Math.PI * 6.2 * t);

      const targetLean = mode === "freeze" ? 5 : 0;
      lean += (targetLean - lean) * Math.min(1, dt * 3);

      const bob = -amp * 2.6 * Math.cos(2 * phi);
      set(refs.pelvis.current, `translate(${HIP.x} ${HIP.y + bob})`);
      set(refs.torso.current, `rotate(${-lean} 0 0)`);

      const near = legAngles(phi, amp * 1.05, tremor);
      const far = legAngles(phi + Math.PI + 0.12, amp * 0.9, -tremor * 0.6);
      set(refs.nHip.current, `translate(4 0) rotate(${-near.hip})`);
      set(refs.nKnee.current, `translate(0 ${THIGH}) rotate(${near.knee})`);
      set(refs.nAnkle.current, `translate(0 ${SHIN}) rotate(${near.foot})`);
      set(refs.fHip.current, `translate(-7 0) rotate(${-far.hip})`);
      set(refs.fKnee.current, `translate(0 ${THIGH}) rotate(${far.knee})`);
      set(refs.fAnkle.current, `translate(0 ${SHIN}) rotate(${far.foot})`);

      const glow = refs.glow.current;
      if (glow) glow.setAttribute("opacity", String(mode === "freeze" ? 0.22 + 0.18 * tremEnv : 0.06));

      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pulseMs = Math.round(60000 / Math.max(40, cueBpm));

  return (
    <svg viewBox="0 0 224 300" className="h-full w-auto" aria-label="Gait silhouette" style={{ ["--pulse-ms" as string]: `${pulseMs}ms` } as React.CSSProperties}>
      <defs>
        <linearGradient id="torsoFade" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#c3d4e0" stopOpacity="0.8" />
          <stop offset="0.45" stopColor="#c3d4e0" stopOpacity="0.35" />
          <stop offset="1" stopColor="#c3d4e0" stopOpacity="0.04" />
        </linearGradient>
        <linearGradient id="legNear" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#dbe9f2" />
          <stop offset="1" stopColor="#aebfcc" />
        </linearGradient>
        <radialGradient id="groundGlow">
          <stop offset="0" stopColor="var(--phase)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--phase)" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* ground */}
      <line x1="18" y1="276" x2="206" y2="276" stroke="rgba(255,255,255,0.14)" strokeWidth="1" />
      <ellipse cx="118" cy="276" rx="52" ry="6" fill="rgba(0,0,0,0.5)" />
      <ellipse ref={refs.glow} cx="118" cy="274" rx="46" ry="9" fill="url(#groundGlow)" opacity="0.06" />

      <g ref={refs.pelvis} transform={`translate(${HIP.x} ${HIP.y})`}>
        {/* far leg */}
        <g ref={refs.fHip} opacity="0.6">
          <line x1="0" y1="2" x2="0" y2={THIGH} stroke="#6f8394" strokeWidth="22" strokeLinecap="round" />
          <g ref={refs.fKnee} transform={`translate(0 ${THIGH})`}>
            <circle cx="0" cy="0" r="8" fill="#6f8394" />
            <line x1="0" y1="0" x2="0" y2={SHIN} stroke="#6f8394" strokeWidth="14" strokeLinecap="round" />
            <g ref={refs.fAnkle} transform={`translate(0 ${SHIN})`}>
              <path d="M -8 -2 L 22 -2 Q 27 -2 27 3 L 27 6 Q 27 9 22 9 L -8 9 Q -12 9 -12 4 Z" fill="#6f8394" />
            </g>
          </g>
        </g>

        {/* pelvis + torso (faded upward — lower-body focus) */}
        <g ref={refs.torso}>
          <path
            d="M -22 6 C -24 -22 -20 -56 -14 -84 C -12 -100 -6 -112 4 -118 L 26 -116 C 30 -98 30 -70 27 -40 C 25 -18 24 -4 22 8 C 12 16 -12 16 -22 6 Z"
            fill="url(#torsoFade)"
          />
          <circle cx="12" cy="-134" r="14" fill="#c3d4e0" opacity="0.16" />
          <ellipse cx="0" cy="2" rx="22" ry="13" fill="#c3d4e0" opacity="0.85" />
        </g>

        {/* near leg */}
        <g ref={refs.nHip}>
          <line x1="0" y1="2" x2="0" y2={THIGH} stroke="url(#legNear)" strokeWidth="24" strokeLinecap="round" />
          <g ref={refs.nKnee} transform={`translate(0 ${THIGH})`}>
            <circle cx="0" cy="0" r="9" fill="#c9d9e4" />
            <line x1="0" y1="0" x2="0" y2={SHIN} stroke="url(#legNear)" strokeWidth="16" strokeLinecap="round" />
            {/* ankle wearable */}
            <g className={cueActive ? "wearable-vibe" : undefined} transform={`translate(0 ${SHIN - 12})`}>
              {cueActive && (
                <>
                  <circle className="figure-ring" cx="0" cy="0" r="14" />
                  <circle className="figure-ring" cx="0" cy="0" r="14" style={{ animationDelay: `${pulseMs / 2}ms` }} />
                </>
              )}
              <rect x="-11" y="-4" width="22" height="8" rx="3" fill="var(--phase)" style={{ filter: "drop-shadow(0 0 6px var(--phase))" }} />
              <rect x="-3" y="-2" width="6" height="4" rx="1" fill="#06080d" opacity="0.6" />
            </g>
            <g ref={refs.nAnkle} transform={`translate(0 ${SHIN})`}>
              <path d="M -8 -2 L 23 -2 Q 28 -2 28 3 L 28 6 Q 28 9 23 9 L -8 9 Q -13 9 -13 4 Z" fill="#cfdfe9" />
            </g>
          </g>
        </g>
      </g>
    </svg>
  );
}

function wrap(x: number): number {
  const tau = 2 * Math.PI;
  let v = ((x % tau) + tau) % tau;
  if (v > Math.PI) v -= tau;
  return v;
}
