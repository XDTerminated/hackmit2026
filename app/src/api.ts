// Client for the device API in docs/api.md. REST for settings, history and actions;
// one WebSocket for live state. The device is the source of truth: this file never
// decides anything, it only asks and listens.

// The UNO Q on the HackMIT network. It changes with the network: set it in Settings on the phone.
export const DEFAULT_HOST = '10.189.75.80:8000';

export type DeviceState = 'still' | 'walking' | 'freeze_detected';

export type Status = {
  device_time: string;
  sensor_ok: boolean;
  sample_rate_hz: number;
  state: DeviceState;
  cue_active: boolean;
  paused_until: string | null;
  events_today: number;
  uptime_s: number;
  firmware: string;
  source?: string;
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
  feedback: null | 'real' | 'false_alarm';
};

export type Settings = {
  detection_enabled: boolean;
  sensitivity: 'catch_more' | 'balanced' | 'fewer_alerts';
  walking_gate: boolean;
  cue_sound: boolean;
  cue_output: 'buzzer' | 'phone';
  cue_vibration: boolean;
  tempo_bpm: number;
  volume: number;
  cue_min_seconds: number;
  log_events: boolean;
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
  | { type: 'cue_started'; device_time: string; event_id: number | null; output: string; tempo_bpm: number; trigger: string }
  | { type: 'cue_stopped'; device_time: string; event_id: number | null; reason: string }
  | { type: 'event_created'; device_time: string; event: FogEvent };

const TIMEOUT_MS = 6000;

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
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`${response.status}: ${detail.slice(0, 200)}`);
      }
      return (await response.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  getStatus = () => this.request<Status>('/status');
  getSettings = () => this.request<Settings>('/settings');
  getEvents = (limit = 200) => this.request<{ events: FogEvent[] }>(`/events?limit=${limit}`);
  getSummary = (days = 14) => this.request<Summary>(`/events/summary?days=${days}`);

  patchSettings = (patch: Partial<Settings>) =>
    this.request<Settings>('/settings', { method: 'PATCH', body: JSON.stringify(patch) });

  // The STOP button: stops the cue and marks the event, in one call (docs/api.md).
  stopCue = (feedback?: 'false_alarm' | 'real') =>
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

  setFeedback = (id: number, feedback: 'false_alarm' | 'real' | null) =>
    this.request<FogEvent>(`/events/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ feedback }),
    });

  // The device's clock may be nonsense after a power cycle; the app owns real time.
  syncTime = () =>
    this.request<{ device_time: string }>('/time', {
      method: 'POST',
      body: JSON.stringify({ now: new Date().toISOString().replace(/\.\d+Z$/, 'Z') }),
    });

  forceFreeze = () => this.request<unknown>('/debug/freeze', { method: 'POST', body: '{}' });
}
