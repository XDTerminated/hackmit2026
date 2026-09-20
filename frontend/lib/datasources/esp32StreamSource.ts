import type { IMUSample } from "@/types";
import type { DataSource, SampleSink } from "./types";

export interface StreamStatus {
  socket: "connecting" | "open" | "closed";
  device: boolean; // ESP32 reported CONNECTED by the backend
  runpod: "ONLINE" | "MOCK";
  grok: "ONLINE" | "MOCK";
  attempts: number;
  lastMessageAt: number | null;
}

/**
 * WebSocket client for the FastAPI /ws/imu stream. Reconnects with capped
 * backoff and never throws into the UI. Samples are only forwarded when the
 * backend reports a real ESP32, so backend demo state can't overwrite the UI.
 */
export class ESP32StreamSource implements DataSource {
  readonly kind = "LIVE" as const;
  private sock: WebSocket | null = null;
  private retry: number | null = null;
  private backoff = 2000;
  private closed = true;
  private sink: SampleSink | null = null;
  status: StreamStatus = { socket: "closed", device: false, runpod: "MOCK", grok: "MOCK", attempts: 0, lastMessageAt: null };

  constructor(
    private readonly url: string,
    private readonly onStatus: (s: StreamStatus) => void,
  ) {}

  start(sink: SampleSink) {
    this.sink = sink;
    if (!this.closed) return;
    this.closed = false;
    this.connect();
  }

  stop() {
    this.closed = true;
    if (this.retry) window.clearTimeout(this.retry);
    this.retry = null;
    this.sock?.close();
    this.sock = null;
    this.emit({ socket: "closed", device: false });
  }

  private emit(patch: Partial<StreamStatus>) {
    this.status = { ...this.status, ...patch };
    this.onStatus(this.status);
  }

  private connect() {
    if (this.closed) return;
    this.emit({ socket: "connecting", attempts: this.status.attempts + 1 });
    let sock: WebSocket;
    try {
      sock = new WebSocket(this.url);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.sock = sock;
    sock.onopen = () => {
      this.backoff = 2000;
      this.emit({ socket: "open" });
    };
    sock.onclose = () => {
      this.emit({ socket: "closed", device: false });
      this.scheduleRetry();
    };
    sock.onerror = () => {
      /* onclose follows */
    };
    sock.onmessage = (ev) => {
      let msg: { type: string; data: unknown };
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "status") {
        const st = msg.data as { esp32?: string; runpod?: string; grok?: string };
        this.emit({
          device: st.esp32 === "CONNECTED",
          runpod: st.runpod === "ONLINE" ? "ONLINE" : "MOCK",
          grok: st.grok === "ONLINE" ? "ONLINE" : "MOCK",
          lastMessageAt: Date.now(),
        });
      } else if (msg.type === "imu" && this.status.device && this.sink) {
        this.status.lastMessageAt = Date.now();
        this.sink(msg.data as IMUSample);
      }
    };
  }

  private scheduleRetry() {
    if (this.closed) return;
    this.retry = window.setTimeout(() => this.connect(), this.backoff);
    this.backoff = Math.min(this.backoff * 2, 15000);
  }
}
