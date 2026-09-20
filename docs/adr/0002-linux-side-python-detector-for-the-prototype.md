# The prototype's detector is Linux-side Python, not C on the STM32

`backend/arduino/README.md` and `test_vectors/README.md` describe the target as a hardware-free C detector
(`backend/arduino/detector/`) running on the UNO Q's STM32. For the HackMIT prototype we are instead running
`backend/api/streaming_detector.py` on the UNO Q's Linux side, in the same process that serves the
API and owns the event log. The reference implementation is already verified frame-for-frame
against the batch evaluation on all 35,405 Daphnet frames, so this removes porting risk entirely
from a fixed-deadline build; the C port's real payoffs — battery life and cueing without Linux
booted — are not prototype concerns.

**This is a deferral, not a cancellation.** `backend/arduino/detector/` and the four test vectors remain the
plan of record; read this before assuming the C port was simply never finished.

## Consequences

- The STM32's only job is delivering milli-g samples at a steady 64 Hz over the Bridge to Linux.
  That remains the hardest unsolved hardware problem, and this decision does not help with it.
- Cue latency now includes the STM32 -> Linux hop and Python scheduling jitter. It must be measured;
  if it is not small against the 1.8 s detection latency, revisit this.
- Linux must be booted and the Python process running for the device to cue at all, so boot time and
  process supervision become part of the demo, in a way they would not be with C on the STM32.
- The test vectors lose their consumer for now. Keep running them against the Python reference so
  the contract stays live for whoever writes the C.
