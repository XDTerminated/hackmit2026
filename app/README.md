# app

Companion mobile app: shows freeze events over time for the wearer and their doctor or physio.
Not scaffolded yet.

## Recommended stack: Expo (React Native)

- The app's job is to read events from the device and chart them. The device's Linux side will
  serve an HTTP API over Wi-Fi, so the app needs no native code to start with, and Expo Go lets you
  run it on a phone without Xcode or Android Studio.
- If Bluetooth is needed later, Expo supports it through a development build
  (`react-native-ble-plx`), without ejecting.
- Tauri's mobile support is newer and its plugin ecosystem much thinner. Tauri makes more sense
  for a desktop dashboard than for a phone app.

Scaffold from the repo root with `npx create-expo-app@latest app` (move this README aside first;
the tool wants an empty folder).

## Contract with the device

The API is drafted in `../docs/api.md` (settings, sensitivity presets, actions, status, events).
Develop against a mock server that replays Daphnet detections so the app does not wait on hardware. Event fields from the project
brief: timestamp, duration, detection confidence, cue type played, whether walking resumed within a
few seconds.
