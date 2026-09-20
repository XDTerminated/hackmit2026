// The live screen. Calm when nothing is happening; one enormous STOP button when a cue
// is playing. Stopping an automatic cue also marks it a false alarm, with an undo -- the
// wearer may have stopped a cue during a real freeze, and that verdict is the only ground
// truth the device will ever get. A beat the wearer asked for is simply stopped.

import { useEffect, useRef, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { Button, Card, Label, Notice } from '../components/ui';
import { Theme } from '../theme';
import { Device } from '../useDevice';

const STATE_TEXT: Record<string, { title: string; note: string }> = {
  still: { title: 'Still', note: 'No walking detected right now.' },
  walking: { title: 'Walking', note: 'Watching for a freeze.' },
  freeze_detected: { title: 'Cueing', note: 'A freeze was detected. Follow the beat.' },
};

const UNDO_SECONDS = 20; // long enough for someone whose movement is slowed

export function NowScreen({ theme, device }: { theme: Theme; device: Device }) {
  const { status, cue, settings, stopCue } = device;
  const [undoId, setUndoId] = useState<number | null>(null);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (undoTimer.current) clearTimeout(undoTimer.current);
  }, []);

  const automatic = cue?.trigger === 'auto';

  const onStop = async () => {
    const id = await stopCue(automatic ? 'false_alarm' : undefined);
    if (!automatic || id == null) return;
    setUndoId(id);
    if (undoTimer.current) clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setUndoId(null), UNDO_SECONDS * 1000);
  };

  const onUndo = async () => {
    if (undoId == null) return;
    // Keep the offer on screen if the device did not take it; the error line says why.
    if (await device.setFeedback(undoId, 'real')) setUndoId(null);
  };

  const paused = status?.paused_until ? new Date(status.paused_until) > new Date() : false;
  const watching = settings?.detection_enabled !== false && !paused;
  const copy = STATE_TEXT[status?.state ?? 'still'] ?? STATE_TEXT.still;

  return (
    <ScrollView
      contentContainerStyle={{ padding: theme.space(2), gap: theme.space(2) }}
      showsVerticalScrollIndicator={false}
    >
      {cue ? (
        <Card theme={theme} style={{ backgroundColor: theme.c.accentSoft, borderColor: theme.c.accent }}>
          <Label theme={theme}>{cue.trigger === 'test' ? 'Testing the cue' : 'Cue playing'}</Label>
          <Text style={{ ...theme.font.title, color: theme.c.text, marginTop: theme.space(0.5) }}>
            {cue.tempoBpm} beats per minute
            {cue.output === 'phone' ? ' · on this phone' : ' · on the device'}
          </Text>
          {cue.trigger === 'test' ? null : (
            <View style={{ marginTop: theme.space(2) }}>
              <Button
                theme={theme}
                kind="solid"
                size="large"
                title={automatic ? 'STOP — this was not a freeze' : 'STOP'}
                onPress={onStop}
              />
            </View>
          )}
        </Card>
      ) : (
        <Card theme={theme}>
          <Label theme={theme}>Right now</Label>
          <Text style={{ ...theme.font.hero, color: theme.c.text, marginTop: theme.space(0.5) }}>
            {copy.title}
          </Text>
          <Text style={{ ...theme.font.body, color: theme.c.muted }}>
            {status?.state === 'walking' && !watching ? 'Detection is off.' : copy.note}
          </Text>
        </Card>
      )}

      {undoId != null ? (
        <Card theme={theme}>
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: theme.space(2),
            }}
          >
            <Text style={{ ...theme.font.body, color: theme.c.text, flex: 1 }}>
              Marked as a false alarm.
            </Text>
            <Button theme={theme} title="Undo" onPress={onUndo} />
          </View>
        </Card>
      ) : null}

      {settings?.cue_output === 'phone' && !cue ? (
        <Text style={{ ...theme.font.label, color: theme.c.muted, textAlign: 'center' }}>
          Cues play on this phone. Keep the app open: a locked phone cannot play one.
        </Text>
      ) : null}

      {status && !status.sensor_ok ? (
        <Notice
          theme={theme}
          urgent
          title="Sensor not responding"
          text="The device is not getting movement data, so it cannot detect a freeze. Check the sensor's wires and strap."
        />
      ) : null}

      {settings && !settings.detection_enabled ? (
        <Notice
          theme={theme}
          title="Detection is off"
          text="The device will not start a cue by itself. Turn detection on in Settings."
        />
      ) : null}

      {paused ? (
        <Notice
          theme={theme}
          title="Paused"
          text={`Detection is off until ${new Date(status!.paused_until!).toLocaleTimeString()}.`}
        >
          <Button theme={theme} title="Resume now" onPress={device.resume} />
        </Notice>
      ) : null}

      <Card theme={theme}>
        <Label theme={theme}>Today</Label>
        <Text style={{ ...theme.font.title, color: theme.c.text, marginTop: 4 }}>
          {status?.events_today ?? 0} cue{status?.events_today === 1 ? '' : 's'}
        </Text>
        <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: theme.space(1) }}>
          Sensitivity: {settings?.sensitivity.replace('_', ' ') ?? '—'} · sample rate{' '}
          {status?.sample_rate_hz ?? '—'} Hz
        </Text>
        {settings?.tempo_auto && status?.cadence_spm ? (
          <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 4 }}>
            Your walking pace: {status.cadence_spm} steps a minute. Cues play at {status.cue_tempo_bpm ?? status.cadence_spm}.
          </Text>
        ) : null}
        {status && Math.abs(status.sample_rate_hz - 64) > 1 ? (
          <Text style={{ ...theme.font.label, color: theme.c.text, marginTop: 4 }}>
            Sample rate has drifted from 64 Hz — the detector's frequency bands are off.
          </Text>
        ) : null}
      </Card>

      <View style={{ gap: theme.space(1) }}>
        <Button theme={theme} title="Start a beat for me" onPress={() => device.startBeat(10)} />
        <Text style={{ ...theme.font.label, color: theme.c.muted, textAlign: 'center' }}>
          Plays the metronome for 10 seconds, whether or not a freeze was detected.
        </Text>
      </View>
    </ScrollView>
  );
}
