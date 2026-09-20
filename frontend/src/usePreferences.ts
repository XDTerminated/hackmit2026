// What this phone remembers between launches: how the app should look, and where the device is.
// Everything else belongs to the device (docs/api.md) and is never stored here.

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';
import { AppState } from 'react-native';
import { Scheme, schemeFor, ThemeMode } from './theme';

const THEME_KEY = 'theme_mode';
const HOST_KEY = 'device_host';
const MODES: ThemeMode[] = ['auto', 'light', 'dark'];

export type Preferences = ReturnType<typeof usePreferences>;

export function usePreferences() {
  const [ready, setReady] = useState(false);
  const [themeMode, setMode] = useState<ThemeMode>('auto');
  const [savedHost, setSavedHost] = useState<string | null>(null);

  useEffect(() => {
    AsyncStorage.multiGet([THEME_KEY, HOST_KEY])
      .then(([[, mode], [, host]]) => {
        if (MODES.includes(mode as ThemeMode)) setMode(mode as ThemeMode);
        if (host) setSavedHost(host);
      })
      .catch(() => {}) // nothing stored, or storage unavailable: the defaults are fine
      .finally(() => setReady(true));
  }, []);

  const setThemeMode = useCallback((mode: ThemeMode) => {
    setMode(mode);
    AsyncStorage.setItem(THEME_KEY, mode).catch(() => {});
  }, []);

  const saveHost = useCallback((host: string) => {
    setSavedHost(host);
    AsyncStorage.setItem(HOST_KEY, host).catch(() => {});
  }, []);

  return { ready, themeMode, setThemeMode, savedHost, saveHost };
}

// Light or dark, right now. In automatic mode the answer changes with the clock, so look again every
// minute and whenever the app comes back to the front.
export function useScheme(mode: ThemeMode): Scheme {
  const [scheme, setScheme] = useState<Scheme>(() => schemeFor(mode, new Date()));

  useEffect(() => {
    const update = () => setScheme(schemeFor(mode, new Date()));
    update();
    if (mode !== 'auto') return;
    const timer = setInterval(update, 60_000);
    const appState = AppState.addEventListener('change', (next) => {
      if (next === 'active') update();
    });
    return () => {
      clearInterval(timer);
      appState.remove();
    };
  }, [mode]);

  return scheme;
}
