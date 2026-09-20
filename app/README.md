# app

Companion app for the freezing-of-gait device: shows the wearer what happened, stops a cue that
fired wrongly, and carries the device's settings. Expo (React Native) + TypeScript, SDK 57.

The device is the source of truth. This app is a viewer and a remote control: it never detects
anything, and everything it shows comes from `../docs/api.md`.

## Running it

Two processes. Start the device server first:

```bash
cd ../analysis
uv run src/device_server.py --seed-days 14          # 1x replay, 14 days of demo history
```

Then the app:

```bash
npm start                                           # scan the QR with Expo Go
```

Both machines must be on the same network. The default device address is baked into
`src/api.ts` (`DEFAULT_HOST`); change it in Settings on the phone, or edit that constant.

For a demo where you cannot wait for a real freeze:

```bash
curl -X POST http://localhost:8000/api/v1/debug/freeze -d '{}'
```

That route exists only in the replay server, never on the board.

## Layout

```
App.tsx                three tabs and the connection banner; no navigation library
src/api.ts             typed client for docs/api.md
src/useDevice.ts       the device link: REST sync, live WebSocket, reconnection, actions
src/theme.ts           colours; nothing in the palette shouts
src/components/ui.tsx  cards, buttons, banner, and the stacked bar chart (react-native-svg)
src/screens/           Now, History, Settings
```

## The three screens

- **Now**: connection, what the device is doing, and when a cue plays, one full-width STOP that
  also marks the event a false alarm, with an undo. Plus a wearer-triggered beat.
- **History**: cues today against yesterday, a 14-day stacked bar chart, and the share of cues
  followed by walking resuming — the only number that argues the device works. Tap a bar for that
  day's cues; tap a cue to mark it a false alarm.
- **Settings**: device address, sensitivity presets with their measured trade-offs, cue output and
  tempo, the walking gate, and pause.

## Decisions worth knowing

- **No push notifications on a freeze.** The cue is the notification.
- **One audible cue source at a time.** Two metronomes on two clocks drift apart, and an unsteady
  beat is worse than none. `cue_output` picks buzzer or phone; the device falls back to the buzzer
  if no app is connected.
- **Stopping a cue never pauses detection.** That is a separate, deliberate action, so the device
  is never silently disarmed.
- **No local database.** History is fetched from the device. Offline history was cut for time; see
  `docs/api.md` for the `since` cursor it would use.
