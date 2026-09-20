// A cue is an aid, never a warning (see CONTEXT.md). Nothing in this palette shouts:
// no red, no alarm colours. A freeze is a data point, not an emergency.

export type Theme = ReturnType<typeof makeTheme>;

const palette = {
  light: {
    bg: '#FBFAF8',
    surface: '#FFFFFF',
    border: '#E4E0DA',
    text: '#1B1A18',
    muted: '#6E6A64',
    accent: '#2F6F62', // the cue colour: deep green, calm and high contrast
    accentSoft: '#DCEAE5',
    auto: '#2F6F62',
    manual: '#7C6FA8',
    falseAlarm: '#C2BCB2',
  },
  dark: {
    bg: '#131312',
    surface: '#1D1D1B',
    border: '#31302D',
    text: '#F3F1ED',
    muted: '#9B968E',
    accent: '#5FBFA8',
    accentSoft: '#1E3A34',
    auto: '#5FBFA8',
    manual: '#A99BDB',
    falseAlarm: '#55524C',
  },
};

export function makeTheme(scheme: string | null | undefined) {
  const c = palette[scheme === 'dark' ? 'dark' : 'light'];
  return {
    c,
    space: (n: number) => n * 8,
    radius: 14,
    font: {
      hero: { fontSize: 56, fontWeight: '300' as const, letterSpacing: -1 },
      title: { fontSize: 22, fontWeight: '600' as const },
      body: { fontSize: 16, fontWeight: '400' as const },
      label: { fontSize: 13, fontWeight: '500' as const, letterSpacing: 0.3 },
    },
  };
}
