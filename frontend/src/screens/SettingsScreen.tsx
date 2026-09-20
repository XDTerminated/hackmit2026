// What the wearer may want to change comes first: the beat, how the app looks, taking a break.
// What someone sets up once (the device's address, how sensitive detection is) sits folded away
// under "Advanced setup".
//
// Settings are the device's, not the app's: every control is a PATCH to the device, and what it
// answers is what gets shown. Only the look of the app is stored on the phone.

import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { Settings } from '../api';
import { Button, Card, ChoiceRow, Label, Row, ToggleRow } from '../components/ui';
import { Theme, ThemeMode } from '../theme';
import { Device } from '../useDevice';
import { Preferences } from '../usePreferences';

const LOOKS: { key: ThemeMode; title: string; note: string }[] = [
  { key: 'auto', title: 'Automatic', note: 'Light during the day, dark in the evening and at night' },
  { key: 'light', title: 'Light', note: 'Always light' },
  { key: 'dark', title: 'Dark', note: 'Always dark' },
];

const SENSITIVITY: { key: Settings['sensitivity']; title: string; note: string }[] = [
  { key: 'catch_more', title: 'Catch more', note: '95% of freezes caught, about 58 false beats an hour. Quickest to respond' },
  { key: 'balanced', title: 'Balanced', note: '93% caught, about 47 false beats an hour' },
  { key: 'fewer_alerts', title: 'Fewer false beats', note: '82% caught, about 23 false beats an hour' },
];

export function SettingsScreen({
  theme,
  device,
  preferences,
}: {
  theme: Theme;
  device: Device;
  preferences: Preferences;
}) {
  const { settings, updateSettings, host, status } = device;
  const [draftHost, setDraftHost] = useState(host);
  const [advanced, setAdvanced] = useState(false);

  return (
    <ScrollView
      contentContainerStyle={{ padding: theme.space(2), gap: theme.space(2) }}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
    >
      {settings ? (
        <Card theme={theme}>
          <Label theme={theme}>The beat</Label>
          <ToggleRow
            theme={theme}
            title="Sound"
            note="A click on every beat"
            value={settings.cue_sound}
            onChange={(on) => updateSettings({ cue_sound: on })}
          />
          <ToggleRow
            theme={theme}
            title="Vibration"
            note="A pulse on every beat. Sound and vibration cannot both be off"
            value={settings.cue_vibration}
            onChange={(on) => updateSettings({ cue_vibration: on })}
          />
          <ToggleRow
            theme={theme}
            title="Match my walking pace"
            note={
              !status?.cadence_spm
                ? 'Not measured yet: walk steadily for about ten seconds.'
                : settings.tempo_auto
                  ? `You walk at about ${status.cadence_spm} steps a minute, so the beat plays at ${status.cue_tempo_bpm ?? status.cadence_spm}.`
                  : `You walk at about ${status.cadence_spm} steps a minute. Turn this on to get the beat at that pace.`
            }
            value={settings.tempo_auto}
            onChange={(on) => updateSettings({ tempo_auto: on })}
          />
          <Row
            theme={theme}
            title={settings.tempo_auto ? 'Speed when your pace is not known' : 'Speed of the beat'}
            note="Beats a minute. A comfortable walking pace; too fast can make walking harder."
          />
          {/* Taps, not a slider: dragging is the hardest gesture with a tremor. */}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: theme.space(1) }}>
            <Button
              theme={theme}
              title="−"
              label="Slower by 5 beats a minute"
              onPress={() => updateSettings({ tempo_bpm: Math.max(60, settings.tempo_bpm - 5) })}
            />
            <Text
              accessibilityLabel={`${settings.tempo_bpm} beats a minute`}
              style={{ ...theme.font.hero, color: theme.c.text, flex: 1, textAlign: 'center' }}
            >
              {settings.tempo_bpm}
            </Text>
            <Button
              theme={theme}
              title="+"
              label="Faster by 5 beats a minute"
              onPress={() => updateSettings({ tempo_bpm: Math.min(140, settings.tempo_bpm + 5) })}
            />
          </View>
          <View style={{ marginTop: theme.space(1) }}>
            <Button theme={theme} title="Try the beat" onPress={device.testCue} />
          </View>
        </Card>
      ) : null}

      <Card theme={theme}>
        <Label theme={theme}>How the app looks</Label>
        {LOOKS.map((look) => (
          <ChoiceRow
            key={look.key}
            theme={theme}
            title={look.title}
            note={look.note}
            selected={preferences.themeMode === look.key}
            onSelect={() => preferences.setThemeMode(look.key)}
          />
        ))}
      </Card>

      {settings ? (
        <Card theme={theme}>
          <Label theme={theme}>Take a break</Label>
          <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 4, marginBottom: theme.space(1) }}>
            For sitting down: in a car, at dinner. It starts again by itself.
          </Text>
          <View style={{ gap: theme.space(1) }}>
            <Button theme={theme} title="Pause for 15 minutes" onPress={() => device.pause(15)} />
            <Button theme={theme} title="Pause for 1 hour" onPress={() => device.pause(60)} />
          </View>
          <ToggleRow
            theme={theme}
            title="Start the beat by itself"
            note="Off: the beat only plays when you ask for it"
            value={settings.detection_enabled}
            onChange={(on) => updateSettings({ detection_enabled: on })}
          />
        </Card>
      ) : null}

      <Card theme={theme}>
        <Row
          theme={theme}
          title="Advanced setup"
          note="For whoever sets the device up. Rarely needs changing."
          onPress={() => setAdvanced((open) => !open)}
          selected={advanced}
          right={<Text style={{ ...theme.font.title, color: theme.c.muted }}>{advanced ? '−' : '+'}</Text>}
        />
        {advanced ? (
          <View style={{ gap: theme.space(1) }}>
            <Label theme={theme}>Device address</Label>
            <TextInput
              value={draftHost}
              onChangeText={setDraftHost}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              placeholder="arduino.local:8000"
              placeholderTextColor={theme.c.muted}
              accessibilityLabel="Device address"
              style={{
                ...theme.font.body,
                color: theme.c.text,
                borderWidth: 2,
                borderColor: theme.c.border,
                borderRadius: theme.radius,
                padding: theme.space(2),
              }}
            />
            <Button theme={theme} title="Connect" onPress={() => device.connectTo(draftHost)} />
            <Text style={{ ...theme.font.label, color: theme.c.muted }}>
              {device.connection === 'online' ? `Connected to ${host}.` : `Not connected to ${host}.`}
              {status
                ? ` Firmware ${status.firmware}, ${status.sample_rate_hz} samples a second, running for ${Math.round(status.uptime_s / 60)} min.`
                : ''}
            </Text>
            {status && Math.abs(status.sample_rate_hz - 64) > 1 ? (
              <Text style={{ ...theme.font.label, color: theme.c.text }}>
                The sensor should deliver 64 samples a second. At this rate the detector is unreliable.
              </Text>
            ) : null}

            {settings ? (
              <>
                <View style={{ marginTop: theme.space(2) }}>
                  <Label theme={theme}>Sensitivity</Label>
                  <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 4 }}>
                    Measured on recordings of people with Parkinson's in a lab, not on this prototype.
                  </Text>
                </View>
                {SENSITIVITY.map((option) => (
                  <ChoiceRow
                    key={option.key}
                    theme={theme}
                    title={option.title}
                    note={option.note}
                    selected={settings.sensitivity === option.key}
                    onSelect={() => updateSettings({ sensitivity: option.key })}
                  />
                ))}
                <ToggleRow
                  theme={theme}
                  title="Only after walking"
                  note="Off: can catch a freeze when starting to walk, but will also play while standing"
                  value={settings.walking_gate}
                  onChange={(on) => updateSettings({ walking_gate: on })}
                />
                <ToggleRow
                  theme={theme}
                  title="Play the beat on this phone"
                  note="The prototype has no sounder of its own: with this off, a beat only blinks the light on the device"
                  value={settings.cue_output === 'phone'}
                  onChange={(on) => updateSettings({ cue_output: on ? 'phone' : 'buzzer' })}
                />
              </>
            ) : null}
          </View>
        ) : null}
      </Card>

      <Text style={{ ...theme.font.label, color: theme.c.muted, textAlign: 'center' }}>
        Not a medical device. Does not diagnose anything. Built for HackMIT 2026.
      </Text>
    </ScrollView>
  );
}
