"use client";

import { useSharedSession } from "@/lib/useSharedSession";
import { PHASE_CLASS, PHASE_COLOR } from "@/lib/format";
import AdvancedPanel from "./AdvancedPanel";
import CurrentState from "./CurrentState";
import DemoControls from "./DemoControls";
import GaitSignal from "./GaitSignal";
import ModeBadge from "./ModeBadge";
import OutcomePanel from "./OutcomePanel";
import ResponsePanel from "./ResponsePanel";

export default function Dashboard() {
  const { state, cadence, latest, samplesRef, startDemo, triggerFreeze, reset, armCue, setSource, selectReplay, replayLabeledEvent } =
    useSharedSession();
  const phaseClass = PHASE_CLASS[state.phase];
  const color = PHASE_COLOR[state.phase];

  return (
    <div className={`stage ${phaseClass}`} data-phase={state.phase}>
      <div className="relative z-10 mx-auto flex max-w-[1680px] flex-col px-4 pb-24 pt-3 sm:px-6">
        <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 bg-black/30">
              <span className="h-3 w-3 rounded-full phase-bg shadow-[0_0_16px_var(--phase)]" />
            </div>
            <div>
              <h1 className="value-display text-xl font-bold leading-none tracking-wide text-white">FoG CUEING LAB</h1>
              <p className="mt-1 font-mono text-[9.5px] uppercase tracking-[0.26em] text-white/45">
                Sense · Detect · Cue · Recover · Adapt
              </p>
            </div>
          </div>
          <ModeBadge state={state} onSource={setSource} />
        </header>

        <div className="grid grid-cols-1 gap-3 xl:grid-cols-12 xl:grid-rows-[minmax(280px,auto)_auto]">
          <div className="xl:col-span-5">
            <CurrentState
              phase={state.phase}
              storyStep={state.storyStep}
              cadence={cadence}
              baseline={state.baseline_cadence_bpm}
              cueActive={state.cue.active}
              cueBpm={state.cue.bpm}
            />
          </div>
          <div className="min-h-[260px] xl:col-span-7">
            <GaitSignal
              samplesRef={samplesRef}
              cadence={cadence}
              baseline={state.baseline_cadence_bpm}
              phase={state.phase}
              color={color}
              source={state.source}
              markers={state.markers}
              replay={state.source === "REPLAY" ? state.replay.loaded : null}
              replayIndex={state.replay.index}
              deviceConnected={state.connections.esp32 === "CONNECTED"}
            />
          </div>
          <div className="xl:col-span-7">
            <ResponsePanel state={state} />
          </div>
          <div className="xl:col-span-5">
            <OutcomePanel analysis={state.analysis} phase={state.phase} cue={state.cue} recovery={state.recovery} onArm={armCue} />
          </div>
        </div>

        <div className="mt-3">
          <AdvancedPanel state={state} latest={latest} />
        </div>

        <p className="mt-3 font-mono text-[9.5px] uppercase tracking-[0.2em] text-white/35">
          Research / assistive-technology prototype. Demo freeze-like events may be simulated or replayed from labeled data. Not a medical device.
        </p>
      </div>

      <DemoControls
        state={state}
        onStart={startDemo}
        onTrigger={triggerFreeze}
        onReset={reset}
        onReplay={() => void replayLabeledEvent()}
        onNextSample={() => selectReplay(1)}
      />
    </div>
  );
}
