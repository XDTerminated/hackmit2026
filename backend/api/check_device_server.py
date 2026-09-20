"""Check the device server's cue safety behaviour against a live, deterministic fake sensor.

Starts device_server the way the board does (start_on_board, LiveSource) with a throwaway event
log, feeds it 20 s of walking-like motion followed by a long steady tremble, and checks:

  1. STOP with nothing playing answers stopped: false and names no event
  2. status carries the active cue, so an app connecting mid-cue can show STOP
  3. STOP during a freeze stops the cue and records the wearer's verdict on that event
  4. no new cue starts while the detector is still holding the same freeze
  5. a cue playing on the phone moves to the buzzer when the last app disconnects
  6. the replay-only debug route does not exist
  7. a cue the device took over goes back to the phone when it reconnects
  8. STOP on a beat the wearer asked for does not release the latch of the automatic cue before it
  9. switching detection off during an automatic cue ends it
 10. a stopped beat's timer does not end the next beat; a pause does not end a beat the wearer asked for
 11. malformed requests answer 400, never 500
 12. a server that could not start (port taken) reports itself dead, so main.py can cue by other means
 13. auto tempo: the cue plays at the cadence measured during the walking (1.5 Hz in the magnitude is a
     0.75 Hz stride seen from one shin, i.e. 90 steps a minute), and at tempo_bpm when auto is off

Exits non-zero if any check fails.

Usage: python api/check_device_server.py
"""

import asyncio
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

import numpy as np

os.environ["FOG_DB"] = os.path.join(tempfile.mkdtemp(), "device.sqlite3")   # before importing the server

import device_server  # noqa: E402
import websockets  # noqa: E402

PORT, SPEED, RATE = 8041, 4, 64
API = f"http://127.0.0.1:{PORT}/api/v1"
failures = []


def check(name, ok, detail=""):
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def status_of(path, body):
    """HTTP status of a POST, without raising on 4xx/5xx."""
    try:
        call(path, "POST", body)
        return 200
    except urllib.error.HTTPError as error:
        return error.code


def call(path, method="GET", body=None):
    request = urllib.request.Request(API + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def wait_for(predicate, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        status = call("/status")
        if predicate(status):
            return status
        time.sleep(0.05)
    return None


def main():
    buzzer = []
    source = device_server.start_on_board(cue_hook=lambda on, bpm: buzzer.append(on), port=PORT)

    # A steady tremble keeps the detector continuously positive, so a new cue after STOP can only
    # be the latch failing, not the detector letting go and catching the freeze again.
    t = np.arange(80 * RATE) / RATE
    magnitude = 1000 + np.where(t < 20, 400 * np.sin(2 * np.pi * 1.5 * t), 120 * np.sin(2 * np.pi * 5 * t))

    def sensor():
        n, started = 0, time.monotonic()
        while True:
            for value in magnitude:
                source.push((n * 15625) % 2**32, value, 0.0, 0.0)
                n += 1
                ahead = n / (RATE * SPEED) - (time.monotonic() - started)
                if ahead > 0:
                    time.sleep(ahead)

    threading.Thread(target=sensor, daemon=True).start()
    if not wait_for(lambda s: True, 15):
        raise SystemExit("server did not start")

    stale = call("/cue/stop", "POST", {"feedback": "false_alarm"})
    check("STOP with nothing playing", stale == {"stopped": False, "event_id": None}, str(stale))

    status = wait_for(lambda s: s["cue_active"], 40)
    check("status carries the active cue", bool(status and status["cue"] and status["cue"]["trigger"] == "auto"),
          str(status and status["cue"]))
    check("auto tempo follows the measured cadence",
          bool(status and status["cadence_spm"] == 90 and status["cue"]["tempo_bpm"] == 90),
          str(status and (status["cadence_spm"], status["cue"])))

    stopped = call("/cue/stop", "POST", {"feedback": "false_alarm"})
    events = call("/events?limit=10")["events"]
    verdict = [e["feedback"] for e in events if e["id"] == stopped["event_id"]]
    check("STOP stops the cue and records the verdict", stopped["stopped"] and verdict == ["false_alarm"], str(stopped))

    restarted = wait_for(lambda s: s["cue_active"], 3.0)   # 12 s of data, all inside the tremble
    check("no new cue while the same freeze continues", restarted is None)

    async def phone_goes_away():
        call("/settings", "PATCH", {"cue_output": "phone"})
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/v1/live") as socket:
            await socket.recv()
            call("/cue/start", "POST", {"seconds": 20})
            await asyncio.sleep(0.5)
            on_phone = call("/status")["cue"]["output"] == "phone" and True not in buzzer[-1:]
        await asyncio.sleep(1.0)
        took_over = call("/status")["cue"]["output"] == "buzzer" and buzzer[-1] is True
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/v1/live") as socket:
            first = json.loads(await socket.recv())
            handed_back = first["cue"]["output"] == "phone" and buzzer[-1] is False
        return on_phone, took_over, handed_back

    on_phone, took_over, handed_back = asyncio.run(phone_goes_away())
    check("cue plays on the phone while an app is connected", on_phone)
    check("buzzer takes over when the last app disconnects", took_over)
    check("the cue goes back to the phone when it reconnects", handed_back)
    call("/cue/stop", "POST", {})

    # The latch again, with a beat in between: needs a fresh automatic cue, i.e. the next tremble of the loop.
    fresh = wait_for(lambda s: s["cue_active"] and s["cue"]["trigger"] == "auto", 40)
    call("/cue/stop", "POST", {})
    call("/cue/start", "POST", {"seconds": 5})
    call("/cue/stop", "POST", {})
    released = wait_for(lambda s: s["cue_active"], 2.0)   # 8 s of data, all inside the same tremble
    check("STOP on a requested beat keeps the automatic cue's latch", bool(fresh) and released is None)

    fresh = wait_for(lambda s: s["cue_active"] and s["cue"]["trigger"] == "auto", 40)
    call("/settings", "PATCH", {"detection_enabled": False})
    ended = wait_for(lambda s: not s["cue_active"], 2.0)
    check("detection switched off ends the automatic cue", bool(fresh) and ended is not None)

    call("/cue/start", "POST", {"seconds": 3})
    call("/cue/stop", "POST", {})
    call("/cue/start", "POST", {"seconds": 20})
    call("/pause", "POST", {"minutes": 5})
    time.sleep(3.6)   # the first beat's 3 s timer has fired by now
    check("a stopped beat's timer and a pause leave the next beat playing", call("/status")["cue_active"])
    call("/cue/stop", "POST", {})
    call("/resume", "POST", {})
    call("/settings", "PATCH", {"detection_enabled": True})

    codes = [status_of("/cue/start", {"seconds": "abc"}), status_of("/pause", {"minutes": None}),
             status_of("/time", {"now": 12345}), status_of("/time", {"now": "2026-09-20T12:00:00"})]
    check("malformed requests answer 400, a time without a zone is read as UTC", codes == [400, 400, 400, 200], str(codes))

    clash = device_server.start_on_board(port=PORT)   # the port is taken: this server cannot start
    time.sleep(3)
    check("a server that could not start reports itself dead", source.alive() and not clash.alive())

    call("/settings", "PATCH", {"tempo_auto": False})
    manual = call("/status")["cue_tempo_bpm"]
    check("manual tempo when auto is off", manual == call("/settings")["tempo_bpm"], str(manual))

    try:
        call("/debug/freeze", "POST", {})
        check("no debug route on the board", False, "route exists")
    except urllib.error.HTTPError as error:
        check("no debug route on the board", error.code == 404)

    print("CHECK " + ("PASSED" if not failures else f"FAILED: {', '.join(failures)}"))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
