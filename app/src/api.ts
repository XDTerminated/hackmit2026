// Client for the device API in docs/api.md. REST for settings, history and actions;
// one WebSocket for live state. The device is the source of truth: this file never
// decides anything, it only asks and listens.

// The UNO Q announces itself as arduino.local (mDNS), which stays the same when the network
// changes; its IP address does not. If the name does not resolve on a phone or network, type the
// IP address in Settings instead (deploy.sh prints it).
// EXPO_PUBLIC_DEVICE_HOST (in app/.env, read by Expo at start) replaces it for development, for example
// with the board's address on the laptop hotspot or a replay server on this machine.
export const DEFAULT_HOST = process.env.EXPO_PUBLIC_DEVICE_HOST ?? 'arduino.local:8000';

type DeviceState = 'still' | 'walking' | 'freeze_detected';

export type Feedback = 'real' | 'false_alarm';

// The cue that is playing, as sent in `status.cue` and in the `cue_started` message.
export type LiveCue = { event_id: number | null; output: string; tempo_bpm: number; trigger: string };

export type Status = {
  device_time: string;
  sensor_ok: boolean;
  sample_rate_hz: number;
  state: DeviceState;
  cue_active: boolean;
  cue: LiveCue | null;
  cadence_spm?: number | null; // the wearer's measured walking cadence, steps per minute
  cue_tempo_bpm?: number; // what a cue starting now would play
  apps_connected?: number;
  paused_until: string | null;
  events_today: number;
  uptime_s: number;
  firmware: string;
  source?: string;
  replay?: boolean; // true when the server replays a recording instead of reading the sensor
};

export type FogEvent = {
  id: number;
  start: string;
  duration_s: number | null;
  trigger: 'auto' | 'manual';
  peak_freeze_index: number | null;
  cue: { sound: boolean; vibration: boolean; output: string; tempo_bpm: number };
  walking_resumed_s: number | null;
  sensitivity: string;
  feedback: Feedback | null;
};

export type Settings = {
  detection_enabled: boolean;
  sensitivity: 'catch_more' | 'balanced' | 'fewer_alerts';
  walking_gate: boolean;
  cue_sound: boolean;
  cue_output: 'buzzer' | 'phone';
  cue_vibration: boolean;
  tempo_auto: boolean;
  tempo_bpm: number;
  cue_min_seconds: number;
};

export type DaySummary = {
  date: string;
  auto: number;
  manual: number;
  false_alarm: number;
  mean_duration_s: number;
  resumed: number;
  with_outcome: number;
};

export type Summary = { days: DaySummary[]; walking_resumed_rate: number | null };

export type LiveMessage =
  | ({ type: 'status'; device_time: string } & Status)
  | ({ type: 'cue_started'; device_time: string } & LiveCue)
  | { type: 'cue_stopped'; device_time: string; event_id: number | null; reason: string }
  | { type: 'event_created'; device_time: string; event: FogEvent };

const TIMEOUT_MS = 6000;

// The device's time format: ISO 8601, UTC, whole seconds.
const isoSeconds = (date: Date) => date.toISOString().replace(/\.\d+Z$/, 'Z');
const HISTORY_DAYS = 14;

// FastAPI answers errors as {"detail": "..."}; show that sentence rather than the raw body.
async function problemText(response: Response) {
  const body = await response.text();
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === 'string') return detail;
  } catch {
    // not JSON: fall through to the raw text
  }
  return `${response.status}: ${body.slice(0, 200)}`;
}

export class DeviceClient {
  constructor(public host: string) {}

  private base() {
    return `http://${this.host}/api/v1`;
  }

  wsUrl() {
    return `ws://${this.host}/api/v1/live`;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(this.base() + path, {
        ...init,
        signal: controller.signal,
        headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
      });
      if (!response.ok) throw new Error(await problemText(response));
      return (await response.json()) as T;
    } catch (problem) {
      // fetch reports a timeout as a bare "Aborted", which tells the wearer nothing.
      if (controller.signal.aborted) throw new Error('The device did not answer.');
      throw problem;
    } finally {
      clearTimeout(timer);
    }
  }

  getStatus = () => this.request<Status>('/status');
  getSettings = () => this.request<Settings>('/settings');
  // Both cover the same HISTORY_DAYS, so every bar in the chart has its events behind it.
  getEvents = () => {
    const since = isoSeconds(new Date(Date.now() - HISTORY_DAYS * 86_400_000));
    return this.request<{ events: FogEvent[] }>(`/events?since=${since}&limit=500`);
  };
  getSummary = () => this.request<Summary>(`/events/summary?days=${HISTORY_DAYS}`);

  patchSettings = (patch: Partial<Settings>) =>
    this.request<Settings>('/settings', { method: 'PATCH', body: JSON.stringify(patch) });

  // The STOP button: stops the cue and marks the event, in one call (docs/api.md).
  stopCue = (feedback?: Feedback) =>
    this.request<{ stopped: boolean; event_id: number | null }>('/cue/stop', {
      method: 'POST',
      body: JSON.stringify(feedback ? { feedback } : {}),
    });

  startCue = (seconds = 10) =>
    this.request<Status>('/cue/start', { method: 'POST', body: JSON.stringify({ seconds }) });

  testCue = () => this.request<unknown>('/cue/test', { method: 'POST', body: '{}' });

  pause = (minutes: number) =>
    this.request<Status>('/pause', { method: 'POST', body: JSON.stringify({ minutes }) });

  resume = () => this.request<Status>('/resume', { method: 'POST', body: '{}' });

  setFeedback = (id: number, feedback: Feedback | null) =>
    this.request<FogEvent>(`/events/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ feedback }),
    });

  // The device's clock may be nonsense after a power cycle; the app owns real time.
  syncTime = () =>
    this.request<{ device_time: string }>('/time', {
      method: 'POST',
      body: JSON.stringify({ now: isoSeconds(new Date()) }),
    });
}
