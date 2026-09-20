// Shared pieces: the connection banner, cards, section headings, and the stacked
// bar chart. Hand-drawn with react-native-svg so the chart owes nothing to a library.

import React from 'react';
import { Pressable, StyleSheet, Switch, Text, View, ViewStyle } from 'react-native';
import Svg, { Circle, G, Line, Path, Rect, Text as SvgText } from 'react-native-svg';
import { DaySummary } from '../api';
import { Connection } from '../useDevice';
import { TARGET, Theme } from '../theme';

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

// Says nothing while all is well. The device's address is a setup detail (Settings, Advanced).
export function ConnectionBanner({
  theme,
  connection,
  replaying,
}: {
  theme: Theme;
  connection: Connection;
  replaying?: string; // name of the recording, when the server is replaying one instead of reading the sensor
}) {
  if (connection === 'online' && !replaying) return null;
  return (
    <View
      accessibilityRole="alert"
      style={{
        backgroundColor: theme.c.accentSoft,
        paddingVertical: theme.space(1.5),
        paddingHorizontal: theme.space(2),
        marginHorizontal: theme.space(2),
        marginBottom: theme.space(1),
        borderRadius: theme.radius,
      }}
    >
      <Text style={{ ...theme.font.body, fontWeight: '600', color: theme.c.text }}>
        {connection === 'online'
          ? `Replaying a recording (${replaying})`
          : connection === 'connecting'
            ? 'Connecting to your device…'
            : 'Not connected to your device'}
      </Text>
      {connection === 'offline' ? (
        <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 2 }}>
          The beat cannot play on this phone until it reconnects. Check that the device is switched on and
          nearby.
        </Text>
      ) : null}
    </View>
  );
}

// The one picture on the home screen: what the device is doing, readable from arm's length.
export function StatusMark({
  theme,
  kind,
  size = 132,
}: {
  theme: Theme;
  kind: 'ready' | 'paused' | 'problem' | 'waiting';
  size?: number;
}) {
  const calm = kind === 'ready';
  const ink = calm ? theme.c.onAccent : theme.c.text;
  return (
    <Svg width={size} height={size} viewBox="0 0 100 100" accessibilityElementsHidden>
      <Circle cx={50} cy={50} r={48} fill={calm ? theme.c.accent : theme.c.accentSoft} />
      {kind === 'ready' ? (
        <Path d="M30 52 L44 66 L72 36" stroke={ink} strokeWidth={8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      ) : null}
      {kind === 'paused' ? (
        <G>
          <Rect x={34} y={30} width={11} height={40} rx={3} fill={ink} />
          <Rect x={55} y={30} width={11} height={40} rx={3} fill={ink} />
        </G>
      ) : null}
      {kind === 'problem' ? (
        <G>
          <Rect x={45} y={24} width={10} height={34} rx={4} fill={ink} />
          <Circle cx={50} cy={72} r={6} fill={ink} />
        </G>
      ) : null}
      {kind === 'waiting' ? (
        <G>
          <Circle cx={30} cy={50} r={6} fill={ink} />
          <Circle cx={50} cy={50} r={6} fill={ink} />
          <Circle cx={70} cy={50} r={6} fill={ink} />
        </G>
      ) : null}
    </Svg>
  );
}

export type TabName = 'Home' | 'My data' | 'Settings';

// Tab icons, drawn here so the app needs no icon font. Always shown with their word.
export function TabIcon({ name, color }: { name: TabName; color: string }) {
  const line = {
    stroke: color,
    strokeWidth: 2.4,
    fill: 'none',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  return (
    <Svg width={28} height={28} viewBox="0 0 28 28" accessibilityElementsHidden>
      {name === 'Home' ? <Path d="M4 13 L14 4 L24 13 M7 11 V23 H21 V11" {...line} /> : null}
      {name === 'My data' ? <Path d="M6 23 V14 M14 23 V6 M22 23 V11" {...line} strokeWidth={4} /> : null}
      {name === 'Settings' ? (
        <G>
          <Path d="M4 8 H24 M4 14 H24 M4 20 H24" {...line} />
          <Circle cx={10} cy={8} r={3} fill={color} />
          <Circle cx={18} cy={14} r={3} fill={color} />
          <Circle cx={9} cy={20} r={3} fill={color} />
        </G>
      ) : null}
    </Svg>
  );
}

// A row of settings text. `right` is the control; a row that is itself the control takes onPress.
export function Row({
  theme,
  title,
  note,
  right,
  onPress,
  role,
  selected,
}: {
  theme: Theme;
  title: string;
  note?: string;
  right?: React.ReactNode;
  onPress?: () => void;
  role?: 'switch' | 'radio' | 'button';
  selected?: boolean;
}) {
  const content = (
    <>
      <View style={{ flex: 1 }}>
        <Text style={{ ...theme.font.body, fontWeight: '600', color: theme.c.text }}>{title}</Text>
        {note ? <Text style={{ ...theme.font.label, color: theme.c.muted, marginTop: 2 }}>{note}</Text> : null}
      </View>
      {right}
    </>
  );
  const style = {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    gap: theme.space(2),
    minHeight: onPress ? TARGET : undefined,
    paddingVertical: theme.space(1),
  };
  if (!onPress) return <View style={style}>{content}</View>;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={role ?? 'button'}
      accessibilityLabel={title}
      accessibilityState={role === 'switch' ? { checked: selected } : { selected }}
      style={({ pressed }) => ({ ...style, opacity: pressed ? 0.6 : 1 })}
    >
      {content}
    </Pressable>
  );
}

// On or off. The whole row is the target: a switch alone is far smaller than a trembling hand needs.
export function ToggleRow({
  theme,
  title,
  note,
  value,
  onChange,
}: {
  theme: Theme;
  title: string;
  note?: string;
  value: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <Row
      theme={theme}
      title={title}
      note={note}
      role="switch"
      selected={value}
      onPress={() => onChange(!value)}
      right={
        <View pointerEvents="none" importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
          <Switch value={value} trackColor={{ true: theme.c.accent, false: theme.c.border }} />
        </View>
      }
    />
  );
}

// One of several. The filled circle says which.
export function ChoiceRow({
  theme,
  title,
  note,
  selected,
  onSelect,
}: {
  theme: Theme;
  title: string;
  note?: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <Row
      theme={theme}
      title={title}
      note={note}
      role="radio"
      selected={selected}
      onPress={onSelect}
      right={
        <View
          style={{
            width: 30,
            height: 30,
            borderRadius: 15,
            borderWidth: 2,
            borderColor: selected ? theme.c.accent : theme.c.muted,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {selected ? (
            <View style={{ width: 16, height: 16, borderRadius: 8, backgroundColor: theme.c.accent }} />
          ) : null}
        </View>
      }
    />
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
          ['Beats', theme.c.auto],
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
  size = 'normal',
  label,
}: {
  theme: Theme;
  title: string;
  onPress: () => void;
  kind?: 'quiet' | 'solid';
  size?: 'normal' | 'large'; // normal is already 14 mm; large is for the one thing on the screen that matters
  label?: string; // spoken by a screen reader when the title is a symbol such as "+"
}) {
  const large = size === 'large';
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label ?? title}
      style={({ pressed }) => ({
        minHeight: large ? 120 : TARGET,
        minWidth: TARGET,
        justifyContent: 'center',
        paddingVertical: theme.space(1.5),
        paddingHorizontal: theme.space(2),
        borderRadius: theme.radius,
        alignItems: 'center',
        backgroundColor: kind === 'solid' ? theme.c.accent : 'transparent',
        borderWidth: kind === 'solid' ? 0 : 2,
        borderColor: theme.c.border,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <Text
        style={{
          ...theme.font.body,
          fontSize: large ? 30 : 20,
          lineHeight: undefined,
          fontWeight: '700',
          textAlign: 'center',
          color: kind === 'solid' ? theme.c.onAccent : theme.c.text,
        }}
      >
        {title}
      </Text>
    </Pressable>
  );
}
