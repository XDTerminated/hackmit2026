# Recording protocol

How to collect labelled data from the device. Nothing runs on a laptop and the phone app is not
needed: the board records to its own storage and serves the files from its diagnostics page.

Volunteers are healthy people simulating freezes. These recordings show that the device works on the
demo scenario and let us tune the amplitude thresholds for our sensor. They say nothing about real
freezes; that evidence comes from the Daphnet and Mendeley datasets.

## Setup

1. Board on the power bank, no USB cable. It starts by itself in about 100 seconds.
2. Sensor on the **outer shin, a hand's width above the ankle, strapped tight**, always the same leg and
   the same way up. A loose sensor wobbles at 3-8 Hz, which is the band the detector reads as freezing.
   Tape the wires: the chip resets if its power dips, and jumper wires on a moving leg will do that.
3. A second person (the labeller) opens `http://arduino.local:7000` on a laptop on the same network as the
   board, or `http://<board-ip>:7000` if the name does not resolve.
4. Before every session, check the tiles: **Sample rate 64.0 Hz** and **Samples lost** not climbing. Have
   the wearer walk a few steps: **Movement power** should jump above 10,000 mg² and drop to tens when
   they stand. If it does not, fix the mounting before recording anything.

## Recording

Type a name (`<person>_<session>`, e.g. `alex_1`), press **Start recording**, and the labeller presses a
key the moment the wearer changes what they are doing: **W** walking, **S** standing, **F** freezing,
**N** no label. Press **Stop recording** at the end. Note the person, leg and anything unusual.

Rules that make the data usable:

- **Hold every state for at least 10 seconds.** The detector looks at 4-second windows; short bouts
  leave no clean windows to score.
- The labeller calls the change out loud ("freeze... now") so the key press and the movement coincide.
- Use **N** for anything that is none of the three: sitting down, adjusting the strap, turning round at a wall.
- A simulated freeze is: walking normally, then stopping abruptly with the feet stuck and the leg
  trembling in place, as if trying to step and failing. Not standing still, and not marching on the spot.

## One session (about 5 minutes per person)

| what | label | how long |
|---|---|---|
| stand still | S | 20 s |
| walk at a normal pace | W | 40 s |
| simulated freeze | F | 10-15 s |
| walk | W | 20 s |
| simulated freeze | F | 10-15 s |
| walk slowly | W | 30 s |
| stand, shifting weight and fidgeting | S | 20 s |
| walk fast | W | 30 s |
| simulated freeze | F | 10-15 s |
| walk with several turns | W | 40 s |
| stand still | S | 20 s |

Two or three people, one or two sessions each, is plenty. Also record one session per person of
**ordinary activity with no freezes** (walking around, sitting down, standing up, stairs if available),
labelled W / S / N: this is what measures false cues.

## After each session

Download the file from the list under the Record panel into `data/own/raw/`, then:

```
cd backend
uv run analysis/check_recording.py ../data/own/raw/<file>.csv
```

Look at it before recording the next person. It must say 64 Hz with no lost samples and gravity near
1000 mg, and the per-label table should show band power in the tens for standing and above 10,000 for
walking. A bad mount or a dropped connection then costs one session, not the afternoon.

Keep **one person's recordings aside and never tune on them**. Thresholds get adjusted on the rest; the
numbers we report come from the untouched set.
