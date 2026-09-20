// Three tabs, a connection banner above them, and one hook owning the device link.
// No navigation library: three screens do not need a router.

import { StatusBar } from 'expo-status-bar';
import React, { useMemo, useState } from 'react';
import {
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from 'react-native';
import { ConnectionBanner } from './src/components/ui';
import { HistoryScreen } from './src/screens/HistoryScreen';
import { NowScreen } from './src/screens/NowScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { makeTheme } from './src/theme';
import { useDevice } from './src/useDevice';
import { useMetronome } from './src/useMetronome';

const TABS = ['Now', 'History', 'Settings'] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const scheme = useColorScheme();
  const theme = useMemo(() => makeTheme(scheme), [scheme]);
  const device = useDevice();
  const [tab, setTab] = useState<Tab>('Now');

  // Lives here, not in a screen: a cue must keep playing while the wearer is looking
  // at their history or their settings.
  useMetronome(device.cue?.output === 'phone', device.cue?.tempoBpm ?? 100);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.c.bg }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ paddingHorizontal: theme.space(2), paddingTop: theme.space(1) }}>
        <Text style={{ ...theme.font.title, color: theme.c.text }}>{tab}</Text>
      </View>
      <ConnectionBanner
        theme={theme}
        connection={device.connection}
        host={device.host}
        source={device.status?.source}
      />
      <View style={{ flex: 1 }}>
        {tab === 'Now' ? <NowScreen theme={theme} device={device} /> : null}
        {tab === 'History' ? <HistoryScreen theme={theme} device={device} /> : null}
        {tab === 'Settings' ? <SettingsScreen theme={theme} device={device} /> : null}
      </View>
      <View
        style={{
          flexDirection: 'row',
          borderTopWidth: StyleSheet.hairlineWidth,
          borderTopColor: theme.c.border,
          backgroundColor: theme.c.surface,
        }}
      >
        {TABS.map((name) => {
          const active = tab === name;
          return (
            <Pressable
              key={name}
              onPress={() => setTab(name)}
              style={{ flex: 1, paddingVertical: theme.space(1.5), alignItems: 'center' }}
            >
              <Text
                style={{
                  ...theme.font.body,
                  fontWeight: active ? '600' : '400',
                  color: active ? theme.c.accent : theme.c.muted,
                }}
              >
                {name}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}
