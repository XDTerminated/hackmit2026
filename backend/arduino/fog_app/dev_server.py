"""Run the Freezing of Gait Monitor web app on a laptop, with no board.

Serves the same page (assets/) and the same /api/... routes as python/main.py does on the
UNO Q, but feeds the detector from a file instead of the Bridge. Standard library + numpy only.

Input (--replay): a CSV whose first columns are either
    ax_mg, ay_mg, az_mg                          (test_vectors/*_input.csv)
    t_us, ax_mg, ay_mg, az_mg, gx, gy, gz[,..]   (a capture or recording from the board)
With no --replay, the four firmware test vectors are played in a loop (real patient data).

Usage: python backend/arduino/fog_app/dev_server.py [--replay FILE] [--speed 1] [--port 7000]
Then open http://localhost:7000
"""

import argparse
import json
import mimetypes
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
ASSETS = APP_DIR / "assets"
sys.path.insert(0, str(APP_DIR / "python"))

from fog_core import SAMPLE_PERIOD_US, SAMPLE_RATE_HZ, FogCore  # noqa: E402

core = FogCore(data_dir=APP_DIR / "data")


def load_rows(path):
    """Rows of (ax, ay, az, gx, gy, gz) from either supported CSV layout."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.strip().split(",")
            try:
                values = [float(v) for v in parts[:7] if v != ""]
            except ValueError:
                continue                       # header, '#' status lines
            if len(values) >= 7:
                rows.append(values[1:7])
            elif len(values) == 3:
                rows.append(values + [0.0, 0.0, 0.0])
    return rows


def replay(rows, speed):
    """Feed rows to the core at 64 Hz * speed, forever, with device-style timestamps."""
    n, started = 0, time.monotonic()
    while True:
        for row in rows:
            core.add_sample((n * SAMPLE_PERIOD_US) % 2**32, *row)
            n += 1
            ahead = n / (SAMPLE_RATE_HZ * speed) - (time.monotonic() - started)
            if ahead > 0:
                time.sleep(ahead)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, download_name=None):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/state":
            self.send_json(core.state(int(query.get("since_sample", 0)), int(query.get("since_frame", 0))))
        elif url.path == "/api/recordings":
            self.send_json(core.list_recordings())
        elif url.path == "/api/recording":
            path = core.recording_path(query.get("name", ""))
            if path is None:
                self.send_json({"error": "no such recording"}, 404)
            else:
                self.send_file(path, download_name=path.name)
        else:
            target = (ASSETS / (url.path.lstrip("/") or "index.html")).resolve()
            if ASSETS.resolve() in target.parents and target.is_file():
                self.send_file(target)
            else:
                self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/record/start":
            self.send_json(core.start_recording(query.get("name", "")))
        elif url.path == "/api/record/stop":
            self.send_json(core.stop_recording())
        elif url.path == "/api/label":
            self.send_json(core.set_label(query.get("label", "")))
        else:
            self.send_json({"error": "not found"}, 404)


class DualStackServer(ThreadingHTTPServer):
    """Listen on IPv6 and IPv4. With IPv4 only, Windows clients using "localhost" try ::1 first
    and lose 2 s per request before falling back."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--replay", help="CSV to replay instead of the test vectors")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed (1 = real time)")
    parser.add_argument("--port", type=int, default=7000)
    args = parser.parse_args()

    if args.replay:
        rows = load_rows(args.replay)
    else:
        vectors = APP_DIR.parents[2] / "test_vectors"
        rows = [r for name in ("walk_then_freeze", "standing_still", "long_freeze", "gate_blocked")
                for r in load_rows(vectors / f"{name}_input.csv")]
    if not rows:
        raise SystemExit("No samples found to replay")

    threading.Thread(target=replay, args=(rows, args.speed), daemon=True).start()
    print(f"Replaying {len(rows)} samples ({len(rows) / SAMPLE_RATE_HZ:.0f} s) at {args.speed:g}x. "
          f"Open http://localhost:{args.port}")
    DualStackServer(("::", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
