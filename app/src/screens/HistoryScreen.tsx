// Wearer-first statistics. Three things, in order of what a wearer actually asks:
// how many today, how the fortnight looks, and -- the only chart that argues the device
// works -- how often walking resumed after a cue.

import { useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, useWindowDimensions, View } from 'react-native';
import { FogEvent } from '../api';
import { Card, DayBars, Label } from '../components/ui';
import { Theme } from '../theme';
import { Device } from '../useDevice';

function dayKey(iso: string) {
  return iso.slice(0, 10);
}

export function HistoryScreen({
  theme,
  device,
}: {
  theme: Theme;
  device: Device;
}) {
  const { summary, events, setFeedback } = device;
  const { width } = useWindowDimensions();
  const [selected, setSelected] = useState<string | null>(null);

  const days = summary?.days ?? [];
  const today = days.length ? days[days.length - 1] : null;
  const yesterday = days.length > 1 ? days[days.length - 2] : null;

  const todayTotal = today ? today.auto + today.manual : 0;
  const yesterdayTotal = yesterday ? yesterday.auto + yesterday.manual : 0;
  const resumedRate = summary?.walking_resumed_rate ?? null;

  const listed = useMemo<FogEvent[]>(() => {
    if (!selected) return [];
    return events.filter((event) => dayKey(event.start) === selected);
  }, [events, selected]);

  const chartWidth = width - theme.space(8); // screen padding 2 + card padding 2, on both sides

  return (
    <ScrollView
      contentContainerStyle={{ padding: theme.space(2), gap: theme.space(2) }}
      showsVerticalScrollIndicator={false}
    >
      <Card theme={theme}>
        <Label theme={theme}>Cues today</Label>
        <Text style={{ ...theme.font.hero, color: theme.c.text }}>{todayTotal}</Text>
        <Text style={{ ...theme.font.body, color: theme.c.muted }}>
          {yesterday
            ? todayTotal === yesterdayTotal
              ? `Same as yesterday (${yesterdayTotal}).`
              : `${todayTotal > yesterdayTotal ? 'More' : 'Fewer'} than yesterday (${yesterdayTotal}).`
            : 'No history yet.'}
        </Text>
      </Card>

      <Card theme={theme}>
        <Label theme={theme}>Last 14 days</Label>
        <View style={{ marginTop: theme.space(1) }}>
          <DayBars
            theme={theme}
            days={days}
            width={chartWidth}
            selected={selected}
            onSelect={(date) => setSelected((current) => (current === date ? null : date))}
          />
        </View>
        <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: theme.space(1) }}>
          Tap a day to see its cues.
        </Text>
      </Card>

      <Card theme={theme}>
        <Label theme={theme}>Walking resumed after a cue</Label>
        <Text style={{ ...theme.font.hero, color: theme.c.text }}>
          {resumedRate == null ? '—' : `${Math.round(resumedRate * 100)}%`}
        </Text>
        <Text style={{ ...theme.font.body, color: theme.c.muted }}>
          Share of cues followed by walking within 15 seconds. False alarms are excluded.
        </Text>
      </Card>

      {selected ? (
        <Card theme={theme}>
          <Label theme={theme}>{selected}</Label>
          {listed.length === 0 ? (
            <Text style={{ ...theme.font.body, color: theme.c.muted, marginTop: theme.space(1) }}>
              No cues stored for this day.
            </Text>
          ) : (
            listed.map((event) => (
              <View
                key={event.id}
                style={{
                  paddingVertical: theme.space(1.5),
                  borderTopWidth: 1,
                  borderTopColor: theme.c.border,
                  gap: 4,
                }}
              >
                <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                  <Text style={{ ...theme.font.body, color: theme.c.text }}>
                    {new Date(event.start).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                    {'  '}
                    {event.duration_s ? `${event.duration_s.toFixed(1)}s` : ''}
                  </Text>
                  <Text style={{ ...theme.font.label, color: theme.c.muted }}>
                    {event.trigger === 'manual' ? 'you started it' : 'detected'}
                  </Text>
                </View>
                <Text style={{ ...theme.font.label, color: theme.c.muted }}>
                  {event.peak_freeze_index != null
                    ? `${event.peak_freeze_index >= 3 ? 'Strong' : 'Weak'} signal`
                    : 'Signal unknown'}
                  {event.walking_resumed_s != null
                    ? ` · walking resumed after ${event.walking_resumed_s.toFixed(1)}s`
                    : ' · walking did not resume within 15s'}
                </Text>
                <Pressable
                  onPress={() =>
                    setFeedback(event.id, event.feedback === 'false_alarm' ? null : 'false_alarm')
                  }
                >
                  <Text
                    style={{
                      ...theme.font.label,
                      color: event.feedback === 'false_alarm' ? theme.c.text : theme.c.accent,
                      marginTop: 2,
                    }}
                  >
                    {event.feedback === 'false_alarm'
                      ? '✓ Marked a false alarm — tap to undo'
                      : 'Mark as a false alarm'}
                  </Text>
                </Pressable>
              </View>
            ))
          )}
        </Card>
      ) : null}

      <Text
        style={{
          ...theme.font.label,
          color: theme.c.muted,
          textAlign: 'center',
          paddingHorizontal: theme.space(2),
        }}
      >
        Not a medical device. Nothing here diagnoses anything.
      </Text>
    </ScrollView>
  );
}
