// The cue itself, when the wearer has chosen to get it on the phone: a click, a vibration
// pulse, or both, on every beat.
//
// One beat every 60000/bpm ms for as long as the cue is active. The beat has to be
// steady -- that is the whole mechanism -- so the interval is re-armed only when the
// tempo actually changes, never on an unrelated re-render. Sound and vibration are read
// through a ref for the same reason: toggling one mid-cue must not restart the beat.

import { setAudioModeAsync, useAudioPlayer } from 'expo-audio';
import * as Haptics from 'expo-haptics';
import { useEffect, useRef } from 'react';
import { Platform, Vibration } from 'react-native';

const CLICK = require('../assets/click.wav');

// Long enough to feel through a pocket, short enough to read as a beat at 140 bpm.
const ANDROID_PULSE_MS = 70;

export type CueChannels = { sound: boolean; vibration: boolean };

function pulse() {
  if (Platform.OS === 'android') {
    // Android honours the duration; its haptics API is too faint to feel while walking.
    Vibration.vibrate(ANDROID_PULSE_MS);
  } else {
    // iOS ignores Vibration's duration (always ~400 ms, which smears into the next beat),
    // so use a single crisp tap instead.
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
  }
}

export function useMetronome(active: boolean, bpm: number, channels: CueChannels) {
  const player = useAudioPlayer(CLICK);
  const playerRef = useRef(player);
  playerRef.current = player;
  const channelsRef = useRef(channels);
  channelsRef.current = channels;

  // iOS silences everything when the ring switch is off, which would make the cue
  // useless in exactly the situation it exists for.
  useEffect(() => {
    setAudioModeAsync({ playsInSilentMode: true }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!active) return;

    const tick = () => {
      try {
        if (channelsRef.current.sound) {
          playerRef.current.seekTo(0);
          playerRef.current.play();
        }
        if (channelsRef.current.vibration) pulse();
      } catch {
        // a missed beat is better than a crashed cue
      }
    };

    tick(); // the first beat lands immediately, not one interval late
    const period = Math.max(200, Math.round(60000 / (bpm || 100)));
    const timer = setInterval(tick, period);
    return () => {
      clearInterval(timer);
      Vibration.cancel();
    };
  }, [active, bpm]);
}
