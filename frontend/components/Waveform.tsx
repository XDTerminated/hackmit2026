"use client";

import { useEffect, useRef, type MutableRefObject } from "react";
import type { IMUSample, Phase } from "@/types";
import type { SignalMarker } from "@/lib/datasources/types";

export interface LabeledRegion {
  from_ms: number;
  to_ms: number;
  label: string;
}

const MARKER_COLOR: Record<SignalMarker["kind"], string> = {
  DETECTION: "#ffb020",
  CUE: "#ff4d6d",
  RECOVERY: "#b6ff4a",
};

const G = 9.81;
const MIN_SPAN = 4.6; // m/s² — keeps a freeze-like collapse looking small

export default function Waveform({
  samplesRef,
  color,
  markers,
  regions,
  windowMs = 10000,
  emptyLabel = "AWAITING SIGNAL",
  minimal = false,
  phase,
}: {
  samplesRef: MutableRefObject<IMUSample[]>;
  color: string;
  markers: SignalMarker[];
  regions?: LabeledRegion[];
  windowMs?: number;
  emptyLabel?: string;
  minimal?: boolean;
  phase?: Phase;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colorRef = useRef(color);
  colorRef.current = color;
  const markersRef = useRef(markers);
  markersRef.current = markers;
  const regionsRef = useRef(regions);
  regionsRef.current = regions;
  const emptyRef = useRef(emptyLabel);
  emptyRef.current = emptyLabel;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let lastCount = 0;
    let lastTs = 0;
    let lastArrival = performance.now();
    let period = 40;
    let yMin = G - MIN_SPAN / 2;
    let yMax = G + MIN_SPAN / 2;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const { width, height } = canvas.getBoundingClientRect();
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const draw = (now: number) => {
      const samples = samplesRef.current;
      const rect = canvas.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const c = colorRef.current;
      const top = minimal ? 52 : 26; // three marker lanes in User Mode
      const plotH = h - top - 6;

      ctx.clearRect(0, 0, w, h);

      if (minimal) {
        const phaseFill = phase === "POSSIBLE_FREEZE" || phase === "DETECTED"
          ? "rgba(237,186,118,0.12)"
          : phase === "CUE_TRIGGERED"
            ? "rgba(239,96,120,0.14)"
          : phase === "RECOVERED"
              ? "rgba(185,233,137,0.14)"
              : phase === "RECOVERY_MONITORING"
                ? "rgba(143,232,219,0.11)"
              : "rgba(143,232,219,0.08)";
        ctx.fillStyle = phaseFill;
        ctx.fillRect(0, top, w, plotH);
        ctx.fillStyle = c;
        ctx.fillRect(0, top, w, 3);
      }

      // The User Mode passes minimal=true so one clear movement trace remains.
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.lineWidth = 1;
      for (let i = 1; i < (minimal ? 1 : 4); i++) {
        const y = top + (plotH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      for (let i = 1; i < (minimal ? 1 : 10); i++) {
        const x = (w / 10) * i;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, h);
        ctx.stroke();
      }

      if (samples.length < 3) {
        ctx.fillStyle = "rgba(255,255,255,0.35)";
        ctx.font = "11px var(--font-mono), monospace";
        ctx.fillText(emptyRef.current, 14, top + 18);
        lastCount = samples.length;
        raf = requestAnimationFrame(draw);
        return;
      }

      const last = samples[samples.length - 1];
      if (samples.length !== lastCount || last.timestamp !== lastTs) {
        const dt = now - lastArrival;
        if (dt > 5 && dt < 400) period = period * 0.85 + dt * 0.15;
        lastArrival = now;
        lastCount = samples.length;
        lastTs = last.timestamp;
      }
      // glide between arrivals instead of stepping
      const tNow = last.timestamp + Math.min(period, now - lastArrival);
      const tStart = tNow - windowMs;
      const xOf = (ts: number) => w - ((tNow - ts) / windowMs) * w;

      // visible slice
      let i0 = samples.length - 1;
      while (i0 > 0 && samples[i0 - 1].timestamp >= tStart) i0--;
      const view = samples.slice(Math.max(0, i0 - 1));

      // adaptive y-range (slow EMA, minimum span, centred on 1 g when small)
      let lo = Infinity;
      let hi = -Infinity;
      let gyMax = 1;
      for (const s of view) {
        if (s.accel_mag < lo) lo = s.accel_mag;
        if (s.accel_mag > hi) hi = s.accel_mag;
        if (s.gyro_mag > gyMax) gyMax = s.gyro_mag;
      }
      let span = Math.max(MIN_SPAN, (hi - lo) * 1.18);
      let mid = (hi + lo) / 2;
      if (hi - lo < MIN_SPAN) mid = mid * 0.4 + G * 0.6;
      const tMin = mid - span / 2;
      const tMax = mid + span / 2;
      yMin += (tMin - yMin) * 0.04;
      yMax += (tMax - yMax) * 0.04;
      span = yMax - yMin;
      const yOf = (v: number) => top + plotH - ((Math.min(yMax, Math.max(yMin, v)) - yMin) / span) * plotH;

      // labeled regions (dataset FoG span)
      for (const r of regionsRef.current || []) {
        const x1 = Math.max(0, xOf(r.from_ms));
        const x2 = Math.min(w, xOf(r.to_ms));
        if (x2 <= 0 || x1 >= w) continue;
        ctx.fillStyle = "rgba(255,176,32,0.07)";
        ctx.fillRect(x1, top, x2 - x1, plotH);
        ctx.strokeStyle = "rgba(255,176,32,0.25)";
        ctx.setLineDash([2, 4]);
        ctx.beginPath();
        ctx.moveTo(x1, top);
        ctx.lineTo(x1, h);
        ctx.moveTo(x2, top);
        ctx.lineTo(x2, h);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(255,176,32,0.55)";
        ctx.font = "9px var(--font-mono), monospace";
        ctx.fillText(r.label, x1 + 6, h - 8);
      }

      // 1 g reference
      if (!minimal) {
        const gY = yOf(G);
        ctx.setLineDash([4, 6]);
        ctx.strokeStyle = "rgba(255,255,255,0.12)";
        ctx.beginPath(); ctx.moveTo(0, gY); ctx.lineTo(w, gY); ctx.stroke();
        ctx.setLineDash([]);
      }
      if (minimal) {
        ctx.strokeStyle = "rgba(255,255,255,0.07)";
        ctx.lineWidth = 1;
        for (const ratio of [0.35, 0.7]) {
          const y = top + plotH * ratio;
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
        }
      }

      // faint gyro magnitude (secondary), bottom 40% of the plot
      if (!minimal) {
        ctx.strokeStyle = "rgba(255,255,255,0.13)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < view.length; i++) {
          const s = view[i];
          const x = xOf(s.timestamp);
          const y = top + plotH - (s.gyro_mag / (gyMax * 1.1)) * plotH * 0.4;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // light EMA on accel to remove sensor jitter but keep morphology
      const pts: { x: number; y: number }[] = [];
      let acc = view[0].accel_mag;
      for (const s of view) {
        // Keep impact shape in User Mode so walking reads as steps rather
        // than a perfect sine wave; Research Mode keeps the softer EMA.
        const sampleWeight = minimal ? 0.78 : 0.5;
        acc = acc * (1 - sampleWeight) + s.accel_mag * sampleWeight;
        pts.push({ x: xOf(s.timestamp), y: yOf(acc) });
      }

      const path = () => {
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        if (minimal) {
          for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
          return;
        }
        for (let i = 1; i < pts.length - 1; i++) {
          const mx = (pts[i].x + pts[i + 1].x) / 2;
          const my = (pts[i].y + pts[i + 1].y) / 2;
          ctx.quadraticCurveTo(pts[i].x, pts[i].y, mx, my);
        }
        const l = pts[pts.length - 1];
        ctx.lineTo(l.x, l.y);
      };

      path();
      ctx.lineTo(pts[pts.length - 1].x, h);
      ctx.lineTo(pts[0].x, h);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, top, 0, h);
      grad.addColorStop(0, hexToRgba(c, 0.3));
      grad.addColorStop(1, hexToRgba(c, 0));
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.save();
      ctx.shadowColor = c;
      ctx.shadowBlur = 16;
      ctx.strokeStyle = hexToRgba(c, 0.5);
      ctx.lineWidth = 4.5;
      ctx.lineJoin = "round";
      path();
      ctx.stroke();
      ctx.restore();

      ctx.strokeStyle = c;
      ctx.lineWidth = 1.8;
      ctx.lineJoin = "round";
      path();
      ctx.stroke();

      const head = pts[pts.length - 1];
      ctx.fillStyle = "#fff";
      ctx.shadowColor = c;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(head.x, head.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // event markers
      ctx.font = "9.5px var(--font-mono), monospace";
      for (const m of markersRef.current) {
        const x = xOf(m.t_ms);
        if (x < -40 || x > w) continue;
        const mc = MARKER_COLOR[m.kind];
        ctx.strokeStyle = hexToRgba(mc, 0.7);
        ctx.setLineDash([3, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, top - 4);
        ctx.lineTo(x, h);
        ctx.stroke();
        ctx.setLineDash([]);
        const label = minimal ? (m.kind === "DETECTION" ? "DETECTED" : m.kind === "RECOVERY" ? "RECOVERED" : "CUE") : m.kind;
        const tw = ctx.measureText(label).width + 12;
        const bx = Math.min(w - tw - 2, Math.max(2, x - tw / 2));
        const markerLane: Record<SignalMarker["kind"], number> = { DETECTION: 3, CUE: 20, RECOVERY: 37 };
        const badgeY = minimal ? markerLane[m.kind] : 4;
        ctx.fillStyle = hexToRgba(mc, 0.16);
        roundRect(ctx, bx, badgeY, tw, 15, 4);
        ctx.fill();
        ctx.strokeStyle = hexToRgba(mc, 0.6);
        roundRect(ctx, bx, badgeY, tw, 15, 4);
        ctx.stroke();
        ctx.fillStyle = mc;
        ctx.fillText(label, bx + 6, badgeY + 11);
        ctx.fillStyle = mc;
        ctx.beginPath();
        ctx.arc(x, top - 2, 2.2, 0, Math.PI * 2);
        ctx.fill();
      }

      // left fade
      const fade = ctx.createLinearGradient(0, 0, w * 0.14, 0);
      fade.addColorStop(0, "rgba(6,8,13,0.95)");
      fade.addColorStop(1, "rgba(6,8,13,0)");
      ctx.fillStyle = fade;
      ctx.fillRect(0, top, w * 0.14, plotH + 6);

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [samplesRef, windowMs, minimal, phase]);

  return <canvas ref={canvasRef} className="h-full w-full" />;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function hexToRgba(hex: string, a: number): string {
  const v = hex.replace("#", "");
  const r = parseInt(v.slice(0, 2), 16);
  const g = parseInt(v.slice(2, 4), 16);
  const b = parseInt(v.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
