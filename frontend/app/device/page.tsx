"use client";

import { useEffect, useState } from "react";
import UserShell from "@/components/UserShell";
import { useSharedSession } from "@/lib/useSharedSession";
import { API_URL } from "@/lib/services";

export default function DevicePage() {
  const { state } = useSharedSession();
  const [calibrating, setCalibrating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!calibrating) return; const id = window.setInterval(() => setProgress((p) => Math.min(100, p + 10)), 1000); return () => window.clearInterval(id); }, [calibrating]);
  async function calibrate() {
    setError(""); setReady(false); setProgress(0); setCalibrating(true);
    try { const res = await fetch(`${API_URL}/api/calibrate`, { method: "POST" }); if (!res.ok) throw new Error(); setReady(true); }
    catch { setError("Calibration could not finish. Check the connection and try again."); }
    finally { setCalibrating(false); }
  }
  const connected = state.source !== "LIVE" || state.connections.esp32 === "CONNECTED";
  const streamReady = state.connections.socket === "open" && (state.source !== "LIVE" || connected);
  return <UserShell title="Device">
    <h1 className="user-page-title">Wearable</h1>
    <p className="user-page-intro">Your ankle device and walking baseline.</p>
    <section className="device-card"><span className="device-icon">◉</span><div><h2>Ankle device</h2><p>{state.source !== "LIVE" ? "Demo device" : connected ? "Connected" : "Disconnected"}</p></div><span className={connected ? "status-dot" : "status-dot offline"} /></section>
    <section className="device-section"><h2>Sensor stream</h2><p>{streamReady ? "Receiving movement data" : "Waiting for movement data"}</p><strong className="device-stream-state">{streamReady ? "LIVE" : "WAITING"}</strong></section>
    <section className="device-section"><h2>Walking baseline</h2><p>Typical cadence</p><strong>{state.source === "LIVE" ? "Not measured" : `${Math.round(state.baseline_cadence_bpm)} BPM`}</strong></section>
    <section className="device-section"><h2>{ready ? "Baseline ready" : "Let’s learn your normal walk"}</h2><p>{state.source === "LIVE" ? "Live calibration will be available when the wearable sends measured cadence." : calibrating ? "Keep walking naturally…" : "Walk naturally for 10 seconds."}</p>
      {calibrating && <progress max="100" value={progress} aria-label="Calibration progress" />}
      <button type="button" className="user-secondary" disabled={calibrating || !connected || state.source === "LIVE"} onClick={() => void calibrate()}>{calibrating ? "Calibrating…" : ready ? "Recalibrate" : "Start calibration"}</button>
      {error && <p role="alert">{error}</p>}
    </section>
  </UserShell>;
}
