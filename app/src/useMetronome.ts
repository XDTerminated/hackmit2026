// The cue itself, when the wearer has chosen to hear it on the phone.
//
// One click every 60000/bpm ms for as long as the cue is active. The beat has to be
// steady -- that is the whole mechanism -- so the interval is re-armed only when the
// tempo actually changes, never on an unrelated re-render.

import { setAudioModeAsync, useAudioPlayer } from 'expo-audio';
import { useEffect, useRef } from 'react';

const CLICK = require('../assets/click.wav');

export function useMetronome(active: boolean, bpm: number) {
  const player = useAudioPlayer(CLICK);
  const playerRef = useRef(player);
  playerRef.current = player;

  // iOS silences everything when the ring switch is off, which would make the cue
  // useless in exactly the situation it exists for.
  useEffect(() => {
    setAudioModeAsync({ playsInSilentMode: true }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!active) return;

    const tick = () => {
      try {
        playerRef.current.seekTo(0);
        playerRef.current.play();
      } catch {
        // a missed click is better than a crashed cue
      }
    };

    tick(); // the first beat lands immediately, not one interval late
    const period = Math.max(200, Math.round(60000 / (bpm || 100)));
    const timer = setInterval(tick, period);
    return () => clearInterval(timer);
  }, [active, bpm]);
}
