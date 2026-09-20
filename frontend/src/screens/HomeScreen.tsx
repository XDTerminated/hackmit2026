// The home screen answers one question: "is it looking after me?" One picture, one sentence, and at
// most two large buttons. No numbers: those live under "My data". When a cue plays, the screen becomes
// the cue -- a beat to watch and one enormous STOP.
//
// Stopping an automatic cue marks it a false alarm (docs/api.md); the wearer can take that back for as
// long as the card is on screen. Nothing here is timed: slowed movement must never cost a choice.

import { Animated, ScrollView, Text, View } from 'react-native';
import { Button, Card, StatusMark } from '../components/ui';
import { Theme } from '../theme';
import { Device } from '../useDevice';

type Mark = 'ready' | 'paused' | 'problem' | 'waiting';
type Action = { title: string; onPress: () => void };

function timeOfDay(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

// What to say, in order of what matters most to the wearer right now.
function describe(device: Device): { mark: Mark; title: string; text: string; action?: Action } {
  const { connection, status, settings } = device;
  if (connection !== 'online' || !status || !settings) {
    return connection === 'offline'
      ? { mark: 'problem', title: 'Not connected', text: 'Check that your device is switched on and nearby.' }
      : { mark: 'waiting', title: 'Connecting', text: 'Looking for your device.' };
  }
  if (!status.sensor_ok) {
    return {
      mark: 'problem',
      title: 'Sensor problem',
      text: 'The device cannot feel your leg moving. Check its strap and wires.',
    };
  }
  if (!settings.detection_enabled) {
    return {
      mark: 'paused',
      title: 'Switched off',
      text: 'The beat will not start by itself.',
      action: { title: 'Switch on', onPress: () => device.updateSettings({ detection_enabled: true }) },
    };
  }
  if (status.paused_until && new Date(status.paused_until) > new Date()) {
    return {
      mark: 'paused',
      title: 'Paused',
      text: `Until ${timeOfDay(status.paused_until)}. The beat will not start by itself.`,
      action: { title: 'Start again now', onPress: device.resume },
    };
  }
  return { mark: 'ready', title: 'Ready', text: 'If your feet get stuck, a beat will play to help you step.' };
}

export function HomeScreen({
  theme,
  device,
  beat,
}: {
  theme: Theme;
  device: Device;
  beat: Animated.Value; // 1 on each beat of a cue this phone is playing, falling back to 0
}) {
  const { cue, settings, stoppedEventId } = device;
  const automatic = cue?.trigger === 'auto';
  const centred = { alignItems: 'center' as const, gap: theme.space(1) };

  if (cue) {
    return (
      <View style={{ flex: 1, padding: theme.space(2), gap: theme.space(3), justifyContent: 'center' }}>
        <View style={centred}>
          <Animated.View
            accessibilityElementsHidden
            style={{
              width: 160,
              height: 160,
              borderRadius: 80,
              backgroundColor: theme.c.accent,
              transform: [{ scale: beat.interpolate({ inputRange: [0, 1], outputRange: [0.8, 1] }) }],
              opacity: beat.interpolate({ inputRange: [0, 1], outputRange: [0.55, 1] }),
            }}
          />
          <Text accessibilityRole="header" style={{ ...theme.font.hero, color: theme.c.text, textAlign: 'center' }}>
            {cue.trigger === 'test' ? 'Testing the beat' : 'Step to the beat'}
          </Text>
          <Text style={{ ...theme.font.body, color: theme.c.muted, textAlign: 'center' }}>
            {cue.output === 'phone' ? 'One step on each beat.' : 'The beat is playing on your device.'}
          </Text>
        </View>
        {cue.trigger === 'test' ? null : (
          <Button
            theme={theme}
            kind="solid"
            size="large"
            title="STOP"
            label={automatic ? 'Stop the beat. This was not a freeze.' : 'Stop the beat'}
            onPress={() => device.stopCue(automatic ? 'false_alarm' : undefined)}
          />
        )}
      </View>
    );
  }

  const now = describe(device);
  const ready = now.mark === 'ready';
  return (
    <ScrollView
      contentContainerStyle={{ flexGrow: 1, padding: theme.space(2), gap: theme.space(3), justifyContent: 'center' }}
      showsVerticalScrollIndicator={false}
    >
      <View style={centred}>
        <StatusMark theme={theme} kind={now.mark} />
        <Text accessibilityRole="header" style={{ ...theme.font.hero, color: theme.c.text, textAlign: 'center' }}>
          {now.title}
        </Text>
        <Text style={{ ...theme.font.body, color: theme.c.muted, textAlign: 'center' }}>{now.text}</Text>
      </View>

      {now.action ? <Button theme={theme} kind="solid" title={now.action.title} onPress={now.action.onPress} /> : null}

      {stoppedEventId != null ? (
        <Card theme={theme}>
          <Text style={{ ...theme.font.body, fontWeight: '600', color: theme.c.text }}>You stopped the beat.</Text>
          <Text style={{ ...theme.font.body, color: theme.c.muted, marginBottom: theme.space(1.5) }}>
            I have noted it as a false alarm. Was that right?
          </Text>
          <View style={{ gap: theme.space(1) }}>
            <Button theme={theme} title="Yes, false alarm" onPress={device.dismissStopped} />
            <Button theme={theme} title="No, I was stuck" onPress={device.confirmRealFreeze} />
          </View>
        </Card>
      ) : null}

      {device.connection === 'online' ? (
        <View style={{ gap: theme.space(1) }}>
          <Button theme={theme} kind={ready ? 'solid' : 'quiet'} title="Play a beat now" onPress={() => device.startBeat(10)} />
          <Text style={{ ...theme.font.label, color: theme.c.muted, textAlign: 'center' }}>
            Plays for 10 seconds.
            {settings?.cue_output === 'phone' ? ' Keep this app open so the beat can play on this phone.' : ''}
          </Text>
        </View>
      ) : null}
    </ScrollView>
  );
}
