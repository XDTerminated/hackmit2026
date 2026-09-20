"use client";

import { useEffect } from "react";
import type { DemoState } from "@/types";

export default function DemoControls({
  state,
  onStart,
  onTrigger,
  onReset,
  onReplay,
  onNextSample,
}: {
  state: DemoState;
  onStart: () => void;
  onTrigger: () => void;
  onReset: () => void;
  onReplay: () => void;
  onNextSample: () => void;
}) {
  const { source, phase, running, replay, connections } = state;
  const idle = phase === "IDLE";
  const sample = replay.index?.events[replay.selected];
  const primaryAction = source === "REPLAY" ? onReplay : onTrigger;
  const primaryDisabled = running || replay.playing || source === "LIVE" || (source === "REPLAY" && !sample);
  const firstAction = source === "REPLAY" ? onNextSample : onStart;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "BUTTON", "SELECT"].includes(target.tagName)) return;
      if (e.key === "1") firstAction();
      else if (e.key === "2" && !primaryDisabled) primaryAction();
      else if (e.key === "3") onReset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [firstAction, primaryAction, primaryDisabled, onReset]);

  return (
    <div className="transport fixed inset-x-0 bottom-0 z-40">
      <div className="mx-auto flex max-w-[1680px] items-center gap-3 px-4 py-2.5 sm:px-6">
        <div className="hidden shrink-0 lg:block">
          <p className="label">{source} mode</p>
          <p className="value-display text-base font-semibold text-white">CONTROLS</p>
          <p className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-white/35">keys 1 · 2 · 3</p>
        </div>
        <div className="grid flex-1 grid-cols-3 gap-2">
          {source === "REPLAY" ? (
            <Btn
              keyLabel="1"
              title="Next replay sample"
              hint={sample ? `${sample.title}` : replay.loadError ? "no replay files found" : "loading index…"}
              onClick={onNextSample}
              disabled={!replay.index}
            />
          ) : (
          <Btn keyLabel="1" title="Start demo" hint={idle ? "Begin realistic walking signal" : "Restart walking"} onClick={onStart} primary={idle && source === "DEMO"} disabled={source === "LIVE"} />
          )}
          <Btn
            keyLabel="2"
            title={source === "REPLAY" ? "Replay labeled event" : "Trigger event"}
            hint={
              running
                ? source === "REPLAY"
                  ? "replaying labeled data…"
                  : "sequence running…"
                : source === "LIVE"
                  ? "events arrive from the device"
                  : source === "REPLAY"
                    ? sample
                      ? `${sample.subject_id} · ${sample.task} · ${sample.fog_severity ?? "FoG"}`
                      : "select a sample"
                    : "runs the full loop automatically"
            }
            onClick={primaryAction}
            disabled={primaryDisabled}
            primary={!idle || source === "REPLAY"}
          />
          <Btn keyLabel="3" title="Reset" hint="clear session" onClick={onReset} />
        </div>
      </div>
    </div>
  );
}

function Btn({
  keyLabel,
  title,
  hint,
  onClick,
  primary,
  disabled,
}: {
  keyLabel: string;
  title: string;
  hint: string;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`transport-btn ${primary && !disabled ? "primary" : ""}`}>
      <span className="key">{keyLabel}</span>
      <span className="min-w-0">
        <span className="value-display block truncate text-[16px] font-semibold leading-tight text-white">{title}</span>
        <span className="block truncate font-mono text-[9.5px] uppercase tracking-[0.16em] text-white/45">{hint}</span>
      </span>
      {primary && !disabled && <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full phase-bg shadow-[0_0_10px_var(--phase)]" />}
    </button>
  );
}
