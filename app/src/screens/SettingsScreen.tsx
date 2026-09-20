// Settings are the device's, not the app's: every control here is a PATCH to the device,
// and the response it sends back is what gets rendered. The app never guesses at state.

import React, { useState } from 'react';
import { ScrollView, Switch, Text, TextInput, View } from 'react-native';
import { Settings } from '../api';
import { Button, Card, Label } from '../components/ui';
import { Theme } from '../theme';
import { Device } from '../useDevice';

const SENSITIVITY: { key: Settings['sensitivity']; title: string; note: string }[] = [
  { key: 'catch_more', title: 'Catch more', note: '95% of freezes caught, ~58 false cues an hour. Fastest to respond' },
  { key: 'balanced', title: 'Balanced', note: '93% caught, ~47 false cues an hour' },
  { key: 'fewer_alerts', title: 'Fewer false cues', note: '82% caught, ~23 false cues an hour' },
];

// A setting that is on or off. The switch is named for screen readers by the row's title.
function ToggleRow({
  theme,
  title,
  note,
  value,
  onChange,
}: {
  theme: Theme;
  title: string;
  note?: string;
  value: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <Row
      theme={theme}
      title={title}
      note={note}
      right={
        <Switch
          value={value}
          onValueChange={onChange}
          accessibilityLabel={title}
          trackColor={{ true: theme.c.accent, false: theme.c.border }}
        />
      }
    />
  );
}

function Row({
  theme,
  title,
  note,
  right,
}: {
  theme: Theme;
  title: string;
  note?: string;
  right: React.ReactNode;
}) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: theme.space(2),
        paddingVertical: theme.space(1),
      }}
    >
      <View style={{ flex: 1 }}>
        <Text style={{ ...theme.font.body, color: theme.c.text }}>{title}</Text>
        {note ? (
          <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 2 }}>{note}</Text>
        ) : null}
      </View>
      {right}
    </View>
  );
}

export function SettingsScreen({
  theme,
  device,
}: {
  theme: Theme;
  device: Device;
}) {
  const { settings, updateSettings, host, status } = device;
  const [draftHost, setDraftHost] = useState(host);

  return (
    <ScrollView
      contentContainerStyle={{ padding: theme.space(2), gap: theme.space(2) }}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
    >
      <Card theme={theme}>
        <Label theme={theme}>Device address</Label>
        <TextInput
          value={draftHost}
          onChangeText={setDraftHost}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="10.0.0.5:8000"
          placeholderTextColor={theme.c.muted}
          style={{
            ...theme.font.body,
            color: theme.c.text,
            borderWidth: 1,
            borderColor: theme.c.border,
            borderRadius: theme.radius,
            padding: theme.space(1.5),
            marginTop: theme.space(1),
          }}
        />
        <View style={{ marginTop: theme.space(1) }}>
          <Button theme={theme} title="Connect and test" onPress={() => device.connectTo(draftHost)} />
        </View>
        {status ? (
          <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: theme.space(1) }}>
            Firmware {status.firmware} · {status.sample_rate_hz} Hz · up{' '}
            {Math.round(status.uptime_s / 60)} min
          </Text>
        ) : null}
      </Card>

      {settings ? (
        <>
          <Card theme={theme}>
            <Label theme={theme}>Sensitivity</Label>
            <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 4 }}>
              Measured on recordings of people with Parkinson's in a lab, not on this prototype.
            </Text>
            {SENSITIVITY.map((option) => {
              const active = settings.sensitivity === option.key;
              return (
                <View key={option.key} style={{ marginTop: theme.space(1) }}>
                  <ToggleRow
                    theme={theme}
                    title={option.title}
                    note={option.note}
                    value={active}
                    onChange={() => updateSettings({ sensitivity: option.key })}
                  />
                </View>
              );
            })}
          </Card>

          <Card theme={theme}>
            <Label theme={theme}>The cue</Label>
            <ToggleRow
              theme={theme}
              title="Play on this phone"
              note="The prototype has no buzzer: with this off, a cue only blinks the light on the device. Keep this app open and on screen, because a locked phone cannot play a cue."
              value={settings.cue_output === 'phone'}
              onChange={(on) => updateSettings({ cue_output: on ? 'phone' : 'buzzer' })}
            />
            <Row
              theme={theme}
              title={`Tempo — ${settings.tempo_bpm} bpm`}
              note="Set it to a comfortable walking rate, ideally with a physio. Too fast can make gait worse."
              right={
                <View style={{ flexDirection: 'row', gap: theme.space(2) }}>
                  <Button
                    theme={theme}
                    title="−"
                    label="Slower by 5 beats per minute"
                    onPress={() =>
                      updateSettings({ tempo_bpm: Math.max(60, settings.tempo_bpm - 5) })
                    }
                  />
                  <Button
                    theme={theme}
                    title="+"
                    label="Faster by 5 beats per minute"
                    onPress={() =>
                      updateSettings({ tempo_bpm: Math.min(140, settings.tempo_bpm + 5) })
                    }
                  />
                </View>
              }
            />
            <ToggleRow
              theme={theme}
              title="Sound"
              note="A click on every beat. Sound and vibration cannot both be off."
              value={settings.cue_sound}
              onChange={(on) => updateSettings({ cue_sound: on })}
            />
            <ToggleRow
              theme={theme}
              title="Vibration"
              note="A pulse on every beat: this phone when the cue plays here, otherwise the device's motor."
              value={settings.cue_vibration}
              onChange={(on) => updateSettings({ cue_vibration: on })}
            />
            <View style={{ marginTop: theme.space(1) }}>
              <Button theme={theme} title="Test the cue" onPress={device.testCue} />
            </View>
          </Card>

          <Card theme={theme}>
            <Label theme={theme}>Detection</Label>
            <ToggleRow
              theme={theme}
              title="Detection on"
              value={settings.detection_enabled}
              onChange={(on) => updateSettings({ detection_enabled: on })}
            />
            <ToggleRow
              theme={theme}
              title="Only cue after walking"
              note="Off: can catch freezes when starting to walk, but will also beep while standing."
              value={settings.walking_gate}
              onChange={(on) => updateSettings({ walking_gate: on })}
            />
            <View style={{ flexDirection: 'row', gap: theme.space(1), marginTop: theme.space(1) }}>
              {[15, 60].map((minutes) => (
                <View key={minutes} style={{ flex: 1 }}>
                  <Button
                    theme={theme}
                    title={`Pause ${minutes} min`}
                    onPress={() => device.pause(minutes)}
                  />
                </View>
              ))}
            </View>
            <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: theme.space(1) }}>
              Pausing is for sitting down. Stopping a cue never pauses detection.
            </Text>
          </Card>
        </>
      ) : null}

      <Text style={{ ...theme.font.label, color: theme.c.muted, textAlign: 'center' }}>
        Not a medical device. Does not diagnose anything. Built for HackMIT 2026.
      </Text>
    </ScrollView>
  );
}
