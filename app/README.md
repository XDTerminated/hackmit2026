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

### Against the real device

The UNO Q runs the same server (`device/fog_app`, deployed with `bash device/fog_app/deploy.sh`), fed by
the IMU instead of a CSV, on port 8000. Put the phone on the same Wi-Fi as the board. The app's default address is `arduino.local:8000`, the
board's mDNS name, which survives a change of network; if it does not resolve, set the address in Settings
to `<board-ip>:8000` (the deploy script prints it, and it changes with every network). Event Wi-Fi often blocks
device-to-device traffic: if the app cannot connect, put the phone and the board on a phone hotspot.
`/debug/freeze` does not exist there; walk, stop and tremble the leg instead.

For a demo where you cannot wait for a real freeze:

```bash
curl -X POST http://localhost:8000/api/v1/debug/freeze -d '{}'
```

That route exists only in the replay server, never on the board.

## Layout

```
App.tsx                three tabs and the connection banner; no navigation library
src/api.ts             typed client for docs/api.md
src/useDevice.ts       the device link: live WebSocket, a REST sync on every connect, reconnection, and
                       every action (failures are shown under the banner on all tabs)
src/theme.ts           colours; nothing in the palette shouts
src/components/ui.tsx  cards, buttons, banner, and the stacked bar chart (react-native-svg)
src/screens/           Now, History, Settings
```

## The three screens

- **On every tab**: the connection banner, and the last error in plain words.
- **Now**: what the device is doing, and when a cue plays, one large STOP. Stopping an
  automatic cue also marks the event a false alarm, with a 20 s undo; a beat the wearer asked for is just
  stopped. Also says so when the sensor has gone quiet or detection is off, shows the wearer's measured
  walking pace, and offers a wearer-triggered beat.
- **History**: cues today against yesterday, a 14-day stacked bar chart, and the share of cues
  followed by walking resuming — the only number that argues the device works. Tap a bar for that
  day's cues; tap a cue to mark it a false alarm.
- **Settings**: device address, sensitivity presets with their measured trade-offs, cue output, "Match my
  walking pace" (auto tempo, with the manual tempo as its fallback), sound and vibration, a 2 s cue test, the
  walking gate, and pause.

## Decisions worth knowing

- **No push notifications on a freeze.** The cue is the notification.
- **The phone cue is a click, a vibration pulse, or both** (Settings: Sound, Vibration), on the same beat.
  Android uses a 70 ms vibration; iOS ignores vibration durations (always ~0.4 s, which smears into the
  next beat), so it gets a single heavy haptic tap per beat instead. Expo Go is enough for both.
- **The phone is the cue.** `cue_output` defaults to `phone`, so the device needs no buzzer. The price: the
  app must be open on screen. It keeps the screen awake for that reason (`expo-keep-awake`), and says so on the
  Now screen. A locked or backgrounded phone plays nothing; see "The limit of a phone cue" in `docs/api.md`.
- **One audible cue source at a time.** Two metronomes on two clocks drift apart, and an unsteady
  beat is worse than none. `cue_output` picks buzzer or phone; the device falls back to the buzzer
  if no app is connected.
- **Stopping a cue never pauses detection.** That is a separate, deliberate action, so the device
  is never silently disarmed.
- **No local database.** History is fetched from the device. Offline history was cut for time; see
  `docs/api.md` for the `since` cursor it would use.
