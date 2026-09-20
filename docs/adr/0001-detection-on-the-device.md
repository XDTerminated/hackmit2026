# Detection runs on the device, not the phone

The detector could run on the phone (the device streams raw milli-g samples over the link and the
app ports `backend/api/streaming_detector.py` to TypeScript) or on the device, with the phone
receiving only events. We chose the device: a cueing aid that goes silent because a phone was in a
bag, out of hotspot range, backgrounded by the OS or out of battery is not a cueing aid. The app is
a viewer and a remote control, and the device is the source of truth for settings and events.

## Consequences

- A port of the detector stays on the device's critical path; the app can never improve detection.
- The cue fires with no network hop in the path, so cue latency is set by the detector alone
  (median 1.8 s on Daphnet) and not by the link.
- Phone-side detection would have let the app be demoed against a raw-sample stream with no device
  firmware at all. We give that up, and pay for it with the mock server (`docs/api.md`) instead,
  which replays real detections behind the real API.
