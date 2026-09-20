// Three tabs and one hook owning the device link. Home is for the wearer; the numbers live under
// "My data"; setup lives at the bottom of Settings. No navigation library: three screens do not
// need a router.

import { useKeepAwake } from 'expo-keep-awake';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Pressable, Text, View } from 'react-native';
// react-native's own SafeAreaView is deprecated and does nothing on Android, where Expo draws
// edge to edge, so the title would sit under the status bar.
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { ConnectionBanner, TabIcon, TabName } from './src/components/ui';
import { HistoryScreen } from './src/screens/HistoryScreen';
import { HomeScreen } from './src/screens/HomeScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { makeTheme, TARGET } from './src/theme';
import { useDevice } from './src/useDevice';
import { useMetronome } from './src/useMetronome';
import { Preferences, usePreferences, useScheme } from './src/usePreferences';

const TABS: TabName[] = ['Home', 'My data', 'Settings'];

function Shell({ preferences }: { preferences: Preferences }) {
  const scheme = useScheme(preferences.themeMode);
  const theme = useMemo(() => makeTheme(scheme), [scheme]);
  const device = useDevice(preferences.savedHost);
  const [tab, setTab] = useState<TabName>('Home');

  // The phone is the cue. A locked or backgrounded phone runs no timers and receives no messages,
  // so it could never start one: keep the screen on for as long as the app is open.
  useKeepAwake();

  // An address that has worked is worth remembering; a typo is not.
  const { saveHost, savedHost } = preferences;
  useEffect(() => {
    if (device.connection === 'online' && device.host !== savedHost) saveHost(device.host);
  }, [device.connection, device.host, savedHost, saveHost]);

  // The beat, for the eyes: set to 1 on every beat and left to fall away, so the circle on the home
  // screen moves with the click and the vibration instead of keeping a clock of its own.
  const beat = useRef(new Animated.Value(0)).current;
  const onBeat = useCallback(() => {
    beat.setValue(1);
    Animated.timing(beat, { toValue: 0, duration: 260, useNativeDriver: true }).start();
  }, [beat]);

  // Lives here, not in a screen: a cue must keep playing while the wearer is looking
  // at their data or their settings.
  useMetronome(
    device.cue?.output === 'phone',
    device.cue?.tempoBpm ?? 100,
    { sound: device.settings?.cue_sound ?? true, vibration: device.settings?.cue_vibration ?? false },
    onBeat,
  );

  // A cue is the one thing that may take the screen over: whatever tab was open, show the beat and STOP.
  const cueStarted = device.cue != null && device.cue.trigger !== 'test';
  useEffect(() => {
    if (cueStarted) setTab('Home');
  }, [cueStarted]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.c.bg }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ paddingHorizontal: theme.space(2), paddingVertical: theme.space(1) }}>
        <Text accessibilityRole="header" style={{ ...theme.font.title, color: theme.c.text }}>
          {tab}
        </Text>
      </View>
      <ConnectionBanner
        theme={theme}
        connection={device.connection}
        replaying={device.status?.replay ? device.status.source : undefined}
      />
      {device.error ? (
        <Text
          accessibilityRole="alert"
          style={{
            ...theme.font.label,
            color: theme.c.text,
            paddingHorizontal: theme.space(2),
            paddingBottom: theme.space(1),
          }}
        >
          {device.error}
        </Text>
      ) : null}
      <View style={{ flex: 1 }}>
        {tab === 'Home' ? <HomeScreen theme={theme} device={device} beat={beat} /> : null}
        {tab === 'My data' ? <HistoryScreen theme={theme} device={device} /> : null}
        {tab === 'Settings' ? <SettingsScreen theme={theme} device={device} preferences={preferences} /> : null}
      </View>
      <View
        accessibilityRole="tablist"
        style={{
          flexDirection: 'row',
          borderTopWidth: 1,
          borderTopColor: theme.c.border,
          backgroundColor: theme.c.surface,
          padding: theme.space(0.5),
          gap: theme.space(0.5),
        }}
      >
        {TABS.map((name) => {
          const active = tab === name;
          const color = active ? theme.c.accent : theme.c.muted;
          return (
            <Pressable
              key={name}
              onPress={() => setTab(name)}
              accessibilityRole="tab"
              accessibilityLabel={name}
              accessibilityState={{ selected: active }}
              style={{
                flex: 1,
                minHeight: TARGET - 12,
                justifyContent: 'center',
                alignItems: 'center',
                gap: 2,
                borderRadius: theme.radius,
                backgroundColor: active ? theme.c.accentSoft : 'transparent',
              }}
            >
              <TabIcon name={name} color={color} />
              <Text style={{ ...theme.font.label, fontWeight: active ? '700' : '500', color }}>{name}</Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

export default function App() {
  // The saved address has to be known before the first connection attempt, and the saved look before
  // the first frame; both arrive within a few milliseconds.
  const preferences = usePreferences();
  return <SafeAreaProvider>{preferences.ready ? <Shell preferences={preferences} /> : null}</SafeAreaProvider>;
}
