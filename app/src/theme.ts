// A cue is an aid, never a warning (see CONTEXT.md). Nothing in this palette shouts:
// no red, no alarm colours. A freeze is a data point, not an emergency.
//
// Sizes follow the design guidelines for people with Parkinson's (Nunes et al. 2015, tested with
// 39 people): tap targets of 14 mm a side, high contrast, little on a screen, nothing that has to
// be done against the clock; and for older adults generally: large type, plain words.

export type Theme = ReturnType<typeof makeTheme>;
export type Scheme = 'light' | 'dark';
export type ThemeMode = 'auto' | 'light' | 'dark';

const palette = {
  light: {
    bg: '#FBFAF8',
    surface: '#FFFFFF',
    border: '#D9D4CC',
    text: '#1B1A18',
    muted: '#5F5B55', // 6.6:1 on bg
    accent: '#2F6F62', // the cue colour: deep green, calm and high contrast
    onAccent: '#FFFFFF', // 5.9:1 on accent
    accentSoft: '#DCEAE5',
    auto: '#2F6F62',
    manual: '#7C6FA8',
    falseAlarm: '#C2BCB2',
  },
  dark: {
    bg: '#131312',
    surface: '#1D1D1B',
    border: '#3A3935',
    text: '#F3F1ED',
    muted: '#ABA69E', // 7.4:1 on bg
    accent: '#5FBFA8',
    onAccent: '#0E1F1B', // 8:1 on accent; white was 2.2:1
    accentSoft: '#1E3A34',
    auto: '#5FBFA8',
    manual: '#A99BDB',
    falseAlarm: '#55524C',
  },
};

// 14 mm is about 88 density-independent points (160 to the inch).
export const TARGET = 88;

// "Automatic" follows the clock, not the phone's setting: light while it is day, dark in the evening
// and at night, when a bright screen in a dim room is unwelcome.
const DAY_STARTS_H = 7;
const DAY_ENDS_H = 19;

export function schemeFor(mode: ThemeMode, now: Date): Scheme {
  if (mode !== 'auto') return mode;
  const hour = now.getHours();
  return hour >= DAY_STARTS_H && hour < DAY_ENDS_H ? 'light' : 'dark';
}

export function makeTheme(scheme: Scheme) {
  return {
    scheme,
    c: palette[scheme],
    space: (n: number) => n * 8,
    radius: 16,
    font: {
      hero: { fontSize: 44, fontWeight: '700' as const, letterSpacing: -0.5 },
      title: { fontSize: 28, fontWeight: '700' as const },
      body: { fontSize: 18, fontWeight: '400' as const, lineHeight: 26 },
      label: { fontSize: 15, fontWeight: '500' as const, lineHeight: 21 },
    },
  };
}
