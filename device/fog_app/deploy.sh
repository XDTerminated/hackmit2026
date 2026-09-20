#!/usr/bin/env bash
# Copy this app to a UNO Q connected by USB and (re)start it. Run from Git Bash:
#     bash device/fog_app/deploy.sh          copy + restart + show logs
#     bash device/fog_app/deploy.sh copy     copy only
#     bash device/fog_app/deploy.sh logs     show logs only
#     bash device/fog_app/deploy.sh stop     stop the app
# Uses the adb that Arduino App Lab installs, so no SSH password or Wi-Fi is needed.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # stop Git Bash rewriting /home/... paths

APP_DIR="$(cygpath -m "$(cd "$(dirname "$0")" && pwd)")"   # adb.exe needs a Windows-style path
REMOTE=/home/arduino/ArduinoApps/fog_app
ADB="$(ls "$LOCALAPPDATA"/Arduino15/packages/arduino/tools/adb/*/adb.exe 2>/dev/null | tail -1)"
[ -n "$ADB" ] || { echo "adb not found; install Arduino App Lab first"; exit 1; }
"$ADB" get-state >/dev/null 2>&1 || { echo "No board found over USB"; exit 1; }

action="${1:-all}"
if [ "$action" = all ] || [ "$action" = copy ]; then
    "$ADB" shell "mkdir -p $REMOTE"
    for item in app.yaml sketch python assets; do "$ADB" push "$APP_DIR/$item" "$REMOTE/" | tail -1; done
    # The device API (what the phone app talks to) lives in analysis/src; ship it next to main.py.
    for file in device_server.py streaming_detector.py cadence.py demo_page.html; do
        "$ADB" push "$APP_DIR/../../analysis/src/$file" "$REMOTE/python/" | tail -1
    done
    "$ADB" shell "rm -rf $REMOTE/python/__pycache__"
fi
if [ "$action" = all ]; then
    # Compiles the sketch, flashes the STM32 and starts the Python side. Slow the first time.
    # stop, then start: "app restart" sometimes fails with "app is running" while the old container winds down
    "$ADB" shell "arduino-app-cli app stop user:fog_app >/dev/null 2>&1; sleep 3; arduino-app-cli app start user:fog_app"
    ip="$("$ADB" shell "ip -4 -o addr show wlan0 | awk '{print \$4}' | cut -d/ -f1" | tr -d '\r')"
    "$ADB" forward tcp:7000 tcp:7000 >/dev/null   # also reachable through the USB cable
    "$ADB" forward tcp:8000 tcp:8000 >/dev/null
    echo; echo "Page: http://localhost:7000 on this laptop (through USB)"
    echo "      http://${ip:-<board-ip>}:7000 from any device on the same Wi-Fi"
    echo "Demo screen: http://localhost:8000/demo (what the detector sees, for a projector)"
    echo "Phone app: device address arduino.local:8000, or ${ip:-<board-ip>}:8000 if the name does not resolve"
    echo "           (the IP changes whenever the board joins a different network)"; echo
fi
if [ "$action" = all ] || [ "$action" = logs ]; then
    "$ADB" shell "arduino-app-cli app logs user:fog_app" | tail -40
fi
if [ "$action" = stop ]; then
    "$ADB" shell "arduino-app-cli app stop user:fog_app"
fi
