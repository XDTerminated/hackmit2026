# device

Everything that runs on the Arduino UNO Q. Nothing is implemented yet; this file records the plan.

## Intended layout

```
device/
  detector/     hardware-free C: detector.h / detector.c, plus a laptop test runner that feeds
                ../test_vectors/*_input.csv and compares against *_expected.csv
  <app lab project>/
                the UNO Q App Lab app: the STM32 sketch (IMU sampling at 64 Hz, calls detector/,
                drives the buzzer) and the Linux-side Python (event log in SQLite, HTTP API for the
                mobile app). Create this with App Lab so the file structure matches what the tool
                expects, then move it here.
```

Keep `detector/` free of Arduino headers. It is the only part with a precise spec
(`../test_vectors/README.md`), and it can be finished and proven correct on a laptop before any
hardware works. The sketch then only has to deliver milli-g samples at a steady 64 Hz.

## Settings the data says matter

- Accelerometer range **+-8 g**. The MPU-9250 defaults to +-2 g; patients' heel strikes reach 4-5 g
  in both datasets, so +-2 g would clip constantly and corrupt the spectrum.
- Sample from a hardware timer, not `delay()`. The detector assumes exactly 64 Hz.
- IMU digital low-pass filter around 20-40 Hz to avoid aliasing.
- Convert to milli-g before the detector: the 178 and 10,000 mg^2 thresholds assume it.
- First milestone is streaming raw samples to the laptop as CSV (`t_ms, acc_x, acc_y, acc_z,
  gyr_x, gyr_y, gyr_z`), so the analysis scripts can be run on your own recordings.

## Not verified yet

UNO Q I2C pin locations, power requirements, the current Bridge/RPC API, and the exact App Lab
project structure. Check the official documentation before wiring or scaffolding.
