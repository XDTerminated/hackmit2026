"use client";

import UserShell from "@/components/UserShell";
import { useSharedSession } from "@/lib/useSharedSession";

export default function ActivityPage() {
  const { state, clearEvents } = useSharedSession();
  const events = state.events.filter((event) => !event.episode_id.startsWith("R")).slice().reverse();
  return <UserShell title="Activity">
    <h1 className="user-page-title">Recent activity</h1>
    <p className="user-page-intro">A simple record of moments when your walking changed.</p>
    <div className="activity-summary"><span>Recorded events</span><strong>{events.length}</strong>{events.length > 0 && <button type="button" className="activity-clear" onClick={() => { if (window.confirm("Clear all activity?")) clearEvents(); }}>Clear activity</button>}</div>
    <div className="activity-list">{events.length ? events.map((event) => <article className="activity-card" key={event.episode_id}>
      <time>{new Date(event.timestamp_iso).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}</time>
      <h2>Movement interruption</h2>
      <p>Rhythmic cue · {event.cue.bpm} BPM</p>
      <div>{event.recovery.detected && event.recovery.time_ms != null ? `Walking resumed · ${(event.recovery.time_ms / 1000).toFixed(2)} s` : "Recovery not recorded"}</div>
    </article>) : <p className="user-empty">No activity recorded yet.</p>}</div>
  </UserShell>;
}
