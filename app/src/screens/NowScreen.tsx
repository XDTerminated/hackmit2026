// The live screen. Calm when nothing is happening; one enormous STOP button when a cue
// is playing. Stopping a cue also marks it a false alarm, with an undo -- the wearer may
// have stopped a cue during a real freeze, and that verdict is the only ground truth the
// device will ever get.

import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { Button, Card, Label } from '../components/ui';
import { Theme } from '../theme';
import { useDevice } from '../useDevice';

const STATE_TEXT: Record<string, { title: string; note: string }> = {
  still: { title: 'Still', note: 'No walking detected right now.' },
  walking: { title: 'Walking', note: 'Watching for a freeze.' },
  freeze_detected: { title: 'Cueing', note: 'A freeze was detected. Follow the beat.' },
};

export function NowScreen({
  theme,
  device,
}: {
  theme: Theme;
  device: ReturnType<typeof useDevice>;
}) {
  const { status, cue, settings, stopCue, client } = device;
  const [undoId, setUndoId] = useState<number | null>(null);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (undoTimer.current) clearTimeout(undoTimer.current);
  }, []);

  const onStop = async () => {
    const id = await stopCue('false_alarm');
    if (id != null) {
      setUndoId(id);
      if (undoTimer.current) clearTimeout(undoTimer.current);
      undoTimer.current = setTimeout(() => setUndoId(null), 8000);
    }
  };

  const onUndo = async () => {
    if (undoId == null) return;
    await device.setFeedback(undoId, 'real');
    setUndoId(null);
  };

  const state = status?.state ?? 'still';
  const copy = STATE_TEXT[state] ?? STATE_TEXT.still;
  const paused = status?.paused_until ? new Date(status.paused_until) > new Date() : false;

  return (
    <ScrollView
      contentContainerStyle={{ padding: theme.space(2), gap: theme.space(2) }}
      showsVerticalScrollIndicator={false}
    >
      {cue ? (
        <Card theme={theme} style={{ backgroundColor: theme.c.accentSoft, borderColor: theme.c.accent }}>
          <Label theme={theme}>Cue playing</Label>
          <Text style={{ ...theme.font.title, color: theme.c.text, marginTop: theme.space(0.5) }}>
            {cue.tempoBpm} beats per minute
            {cue.output === 'phone' ? ' · on this phone' : ' · on the device'}
          </Text>
          <View style={{ marginTop: theme.space(2) }}>
            <Button theme={theme} kind="solid" title="STOP — this was not a freeze" onPress={onStop} />
          </View>
        </Card>
      ) : (
        <Card theme={theme}>
          <Label theme={theme}>Right now</Label>
          <Text style={{ ...theme.font.hero, color: theme.c.text, marginTop: theme.space(0.5) }}>
            {copy.title}
          </Text>
          <Text style={{ ...theme.font.body, color: theme.c.muted }}>{copy.note}</Text>
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

      {paused ? (
        <Card theme={theme}>
          <Label theme={theme}>Paused</Label>
          <Text style={{ ...theme.font.body, color: theme.c.text, marginTop: 4 }}>
            Detection is off until {new Date(status!.paused_until!).toLocaleTimeString()}.
          </Text>
          <View style={{ marginTop: theme.space(1.5) }}>
            <Button theme={theme} title="Resume now" onPress={() => client.resume().then(device.sync)} />
          </View>
        </Card>
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
        {status && Math.abs(status.sample_rate_hz - 64) > 1 ? (
          <Text style={{ ...theme.font.label, color: theme.c.text, marginTop: 4 }}>
            Sample rate has drifted from 64 Hz — the detector's frequency bands are off.
          </Text>
        ) : null}
      </Card>

      <View style={{ gap: theme.space(1) }}>
        <Button
          theme={theme}
          title="Start a beat for me"
          onPress={() => client.startCue(10).catch(() => {})}
        />
        <Text style={{ ...theme.font.label, color: theme.c.muted, textAlign: 'center' }}>
          Plays the metronome for 10 seconds, whether or not a freeze was detected.
        </Text>
      </View>
    </ScrollView>
  );
}
