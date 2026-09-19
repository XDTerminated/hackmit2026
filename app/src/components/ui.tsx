// Shared pieces: the connection banner, cards, section headings, and the stacked
// bar chart. Hand-drawn with react-native-svg so the chart owes nothing to a library.

import React from 'react';
import { Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';
import Svg, { G, Line, Rect, Text as SvgText } from 'react-native-svg';
import { DaySummary } from '../api';
import { Connection } from '../useDevice';
import { Theme } from '../theme';

export function Card({
  theme,
  children,
  style,
}: {
  theme: Theme;
  children: React.ReactNode;
  style?: ViewStyle;
}) {
  return (
    <View
      style={[
        {
          backgroundColor: theme.c.surface,
          borderRadius: theme.radius,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: theme.c.border,
          padding: theme.space(2),
        },
        style,
      ]}
    >
      {children}
    </View>
  );
}

export function Label({ theme, children }: { theme: Theme; children: React.ReactNode }) {
  return (
    <Text style={{ ...theme.font.label, color: theme.c.muted, textTransform: 'uppercase' }}>
      {children}
    </Text>
  );
}

export function ConnectionBanner({
  theme,
  connection,
  host,
  source,
}: {
  theme: Theme;
  connection: Connection;
  host: string;
  source?: string;
}) {
  if (connection === 'online') {
    return (
      <View style={{ paddingHorizontal: theme.space(2), paddingBottom: theme.space(1) }}>
        <Text style={{ ...theme.font.label, color: theme.c.muted }}>
          Connected to {host}
          {source ? ` · replaying ${source}` : ''}
        </Text>
      </View>
    );
  }
  return (
    <View
      style={{
        backgroundColor: theme.c.accentSoft,
        paddingVertical: theme.space(1),
        paddingHorizontal: theme.space(2),
        marginHorizontal: theme.space(2),
        marginBottom: theme.space(1),
        borderRadius: theme.radius,
      }}
    >
      <Text style={{ ...theme.font.label, color: theme.c.text }}>
        {connection === 'connecting' ? `Connecting to ${host}…` : `Not connected to ${host}`}
      </Text>
      {connection === 'offline' ? (
        <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 2 }}>
          The device keeps detecting and cueing on its own. Check the address in Settings.
        </Text>
      ) : null}
    </View>
  );
}

/** Stacked bars: genuine cues, wearer-triggered cues, and cues the wearer called wrong. */
export function DayBars({
  theme,
  days,
  width,
  selected,
  onSelect,
}: {
  theme: Theme;
  days: DaySummary[];
  width: number;
  selected: string | null;
  onSelect: (date: string) => void;
}) {
  const height = 160;
  const padBottom = 22;
  const plot = height - padBottom;
  const max = Math.max(1, ...days.map((d) => d.auto + d.manual + d.false_alarm));
  const slot = width / Math.max(days.length, 1);
  const barWidth = Math.min(slot * 0.62, 22);

  return (
    <View>
      <Svg width={width} height={height}>
        <Line
          x1={0}
          y1={plot + 0.5}
          x2={width}
          y2={plot + 0.5}
          stroke={theme.c.border}
          strokeWidth={1}
        />
        {days.map((day, index) => {
          const x = index * slot + (slot - barWidth) / 2;
          const scale = (value: number) => (value / max) * (plot - 8);
          const falseH = scale(day.false_alarm);
          const manualH = scale(day.manual);
          const autoH = scale(day.auto);
          const isSelected = selected === day.date;
          let y = plot;
          const parts: React.ReactNode[] = [];
          for (const [value, colour, key] of [
            [falseH, theme.c.falseAlarm, 'f'],
            [manualH, theme.c.manual, 'm'],
            [autoH, theme.c.auto, 'a'],
          ] as const) {
            if (value <= 0) continue;
            y -= value;
            parts.push(
              <Rect
                key={key}
                x={x}
                y={y}
                width={barWidth}
                height={value}
                rx={3}
                fill={colour}
                opacity={isSelected || !selected ? 1 : 0.35}
              />,
            );
          }
          return (
            <G key={day.date} onPress={() => onSelect(day.date)}>
              <Rect x={index * slot} y={0} width={slot} height={plot} fill="transparent" />
              {parts}
              <SvgText
                x={index * slot + slot / 2}
                y={height - 6}
                fontSize={9}
                fill={isSelected ? theme.c.text : theme.c.muted}
                textAnchor="middle"
              >
                {day.date.slice(8)}
              </SvgText>
            </G>
          );
        })}
      </Svg>
      <View style={{ flexDirection: 'row', gap: theme.space(2), marginTop: theme.space(1) }}>
        {[
          ['Cues', theme.c.auto],
          ['You started', theme.c.manual],
          ['False alarms', theme.c.falseAlarm],
        ].map(([text, colour]) => (
          <View key={text} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <View style={{ width: 9, height: 9, borderRadius: 2, backgroundColor: colour }} />
            <Text style={{ ...theme.font.label, color: theme.c.muted }}>{text}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export function Button({
  theme,
  title,
  onPress,
  kind = 'quiet',
}: {
  theme: Theme;
  title: string;
  onPress: () => void;
  kind?: 'quiet' | 'solid';
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        paddingVertical: theme.space(1.5),
        paddingHorizontal: theme.space(2),
        borderRadius: theme.radius,
        alignItems: 'center',
        backgroundColor: kind === 'solid' ? theme.c.accent : 'transparent',
        borderWidth: kind === 'solid' ? 0 : StyleSheet.hairlineWidth,
        borderColor: theme.c.border,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <Text
        style={{
          ...theme.font.body,
          fontWeight: '600',
          color: kind === 'solid' ? '#FFFFFF' : theme.c.text,
        }}
      >
        {title}
      </Text>
    </Pressable>
  );
}
