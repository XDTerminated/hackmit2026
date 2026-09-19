# Freezing-of-gait cueing aid

A shin/ankle-worn device that notices a freezing-of-gait episode in someone with a Parkinson's
diagnosis and plays a steady beat to help them start walking again, plus a companion app that
shows what happened. It is a class project, not a medical device, and it diagnoses nothing.

## Language

### The person and the parts

**Wearer**:
The person with a Parkinson's diagnosis who wears the device. Always the subject of the data, and
the primary audience of the app.
_Avoid_: patient, user, subject

**Device**:
The ankle-worn hardware: the IMU, the board that runs the detector, and the buzzer.
_Avoid_: sensor, wearable, board

**App**:
The companion phone app. A viewer and a remote control; the device is the source of truth.
_Avoid_: dashboard, client

### What is detected

**Freeze episode**:
A transient episode in which the wearer's feet stop or tremble in place while they are trying to
walk. The unit the whole project is built around. Detecting one says nothing about whether
somebody has Parkinson's; every number the project quotes was measured on people already diagnosed.
_Avoid_: freeze attack, seizure, Parkinson's detection, diagnosis

**Detection**:
The detector's decision that the current 4-second window looks like a freeze. A detection is a
claim about a window, not about an episode.
_Avoid_: prediction, inference

**Walking gate**:
The condition that the wearer was recently walking, which must hold before a cue may start. It
never governs whether a cue continues.
_Avoid_: walking filter, activity check

**Sensitivity preset**:
A named trade-off between episodes caught and false alarms, chosen by the wearer. The thresholds
behind each preset live on the device and are never set directly from the app.
_Avoid_: threshold, sensitivity level, mode

### What the device does about it

**Cue**:
The steady beat played to help the wearer start walking again. A cue is an aid offered to the
wearer, never a warning about their condition.
_Avoid_: alarm, alert, notification, warning

**Event**:
The stored record of one cue: when it started, how long it ran, and what followed. What the app
charts.
_Avoid_: log entry, session, incident

**False alarm**:
The wearer's judgment that a cue played when they were not freezing. It is their verdict on an
event, and the only ground truth real use will ever produce. Distinct from a **false positive**,
which is one window the detector got wrong, and a **false cue**, which is a cue that played with no
freeze underneath it — the measured rates in the datasets are false cues per hour.
_Avoid_: mistake, error, misfire
