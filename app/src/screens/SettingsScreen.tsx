// Settings are the device's, not the app's: every control here is a PATCH to the device,
// and the response it sends back is what gets rendered. The app never guesses at state.

import React, { useState } from 'react';
import { ScrollView, Switch, Text, TextInput, View } from 'react-native';
import { Settings } from '../api';
import { Button, Card, Label } from '../components/ui';
import { Theme } from '../theme';
import { useDevice } from '../useDevice';

const SENSITIVITY: { key: Settings['sensitivity']; title: string; note: string }[] = [
  { key: 'catch_more', title: 'Catch more', note: '93% of freezes caught, ~58 false cues an hour' },
  { key: 'balanced', title: 'Balanced', note: '91% caught, ~47 false cues an hour' },
  { key: 'fewer_alerts', title: 'Fewer alerts', note: '79% caught, ~19 false cues an hour' },
];

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
  device: ReturnType<typeof useDevice>;
}) {
  const { settings, updateSettings, host, setHost, client, sync, status, error } = device;
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
          <Button theme={theme} title="Connect and test" onPress={() => { setHost(draftHost.trim()); sync(); }} />
        </View>
        {status ? (
          <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: theme.space(1) }}>
            Firmware {status.firmware} · {status.sample_rate_hz} Hz · up{' '}
            {Math.round(status.uptime_s / 60)} min
          </Text>
        ) : null}
        {error ? (
          <Text style={{ ...theme.font.label, color: theme.c.text, marginTop: 4 }}>{error}</Text>
        ) : null}
      </Card>

      {settings ? (
        <>
          <Card theme={theme}>
            <Label theme={theme}>Sensitivity</Label>
            <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 4 }}>
              Measured on Parkinson's patients in a lab, not on this prototype.
            </Text>
            {SENSITIVITY.map((option) => {
              const active = settings.sensitivity === option.key;
              return (
                <View key={option.key} style={{ marginTop: theme.space(1) }}>
                  <Row
                    theme={theme}
                    title={option.title}
                    note={option.note}
                    right={
                      <Switch
                        value={active}
                        onValueChange={() => updateSettings({ sensitivity: option.key })}
                        trackColor={{ true: theme.c.accent, false: theme.c.border }}
                      />
                    }
                  />
                </View>
              );
            })}
          </Card>

          <Card theme={theme}>
            <Label theme={theme}>The cue</Label>
            <Row
              theme={theme}
              title="Play on this phone"
              note="Otherwise the buzzer on the device plays it. Only one at a time: two metronomes drift apart."
              right={
                <Switch
                  value={settings.cue_output === 'phone'}
                  onValueChange={(on) => updateSettings({ cue_output: on ? 'phone' : 'buzzer' })}
                  trackColor={{ true: theme.c.accent, false: theme.c.border }}
                />
              }
            />
            <Row
              theme={theme}
              title={`Tempo — ${settings.tempo_bpm} bpm`}
              note="Set it to a comfortable walking rate, ideally with a physio. Too fast can make gait worse."
              right={
                <View style={{ flexDirection: 'row', gap: theme.space(1) }}>
                  <Button
                    theme={theme}
                    title="−"
                    onPress={() =>
                      updateSettings({ tempo_bpm: Math.max(60, settings.tempo_bpm - 5) })
                    }
                  />
                  <Button
                    theme={theme}
                    title="+"
                    onPress={() =>
                      updateSettings({ tempo_bpm: Math.min(140, settings.tempo_bpm + 5) })
                    }
                  />
                </View>
              }
            />
            <Row
              theme={theme}
              title="Sound"
              note="A click on every beat. Sound and vibration cannot both be off."
              right={
                <Switch
                  value={settings.cue_sound}
                  onValueChange={(on) => updateSettings({ cue_sound: on })}
                  trackColor={{ true: theme.c.accent, false: theme.c.border }}
                />
              }
            />
            <Row
              theme={theme}
              title="Vibration"
              note="A pulse on every beat: this phone when the cue plays here, otherwise the device's motor."
              right={
                <Switch
                  value={settings.cue_vibration}
                  onValueChange={(on) => updateSettings({ cue_vibration: on })}
                  trackColor={{ true: theme.c.accent, false: theme.c.border }}
                />
              }
            />
            <View style={{ marginTop: theme.space(1) }}>
              <Button theme={theme} title="Test the cue" onPress={() => client.testCue().catch(() => {})} />
            </View>
          </Card>

          <Card theme={theme}>
            <Label theme={theme}>Detection</Label>
            <Row
              theme={theme}
              title="Detection on"
              right={
                <Switch
                  value={settings.detection_enabled}
                  onValueChange={(on) => updateSettings({ detection_enabled: on })}
                  trackColor={{ true: theme.c.accent, false: theme.c.border }}
                />
              }
            />
            <Row
              theme={theme}
              title="Only cue after walking"
              note="Off: can catch freezes when starting to walk, but will also beep while standing."
              right={
                <Switch
                  value={settings.walking_gate}
                  onValueChange={(on) => updateSettings({ walking_gate: on })}
                  trackColor={{ true: theme.c.accent, false: theme.c.border }}
                />
              }
            />
            <View style={{ flexDirection: 'row', gap: theme.space(1), marginTop: theme.space(1) }}>
              {[15, 60].map((minutes) => (
                <View key={minutes} style={{ flex: 1 }}>
                  <Button
                    theme={theme}
                    title={`Pause ${minutes} min`}
                    onPress={() => client.pause(minutes).then(sync).catch(() => {})}
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
