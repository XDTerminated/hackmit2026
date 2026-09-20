// One hook owning the link to the device: a WebSocket for live state, a REST sync every time
// that socket opens, and polling while it is down. Every action goes through `attempt`, so a
// failure is shown to the wearer instead of vanishing.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState } from 'react-native';
import {
  DeviceClient,
  DEFAULT_HOST,
  Feedback,
  FogEvent,
  LiveCue,
  LiveMessage,
  Settings,
  Status,
  Summary,
} from './api';

export type Connection = 'connecting' | 'online' | 'offline';
export type Device = ReturnType<typeof useDevice>;

type Cue = { output: string; tempoBpm: number; trigger: string };

const toCue = (cue: LiveCue): Cue => ({ output: cue.output, tempoBpm: cue.tempo_bpm, trigger: cue.trigger });
const describe = (problem: unknown) => (problem instanceof Error ? problem.message : String(problem));

// "10.0.0.5:8000", whatever was pasted: no scheme, no path.
export const normaliseHost = (text: string) =>
  text.trim().replace(/^[a-z]+:\/\//i, '').replace(/\/.*$/, '');

export function useDevice() {
  const [host, setHost] = useState(DEFAULT_HOST);
  const [connection, setConnection] = useState<Connection>('connecting');
  const [status, setStatus] = useState<Status | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [events, setEvents] = useState<FogEvent[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [cue, setCue] = useState<Cue | null>(null);
  const [error, setError] = useState<string | null>(null);

  const client = useMemo(() => new DeviceClient(host), [host]);

  // Bumped whenever the device address changes, so an answer from the old address that arrives
  // late is dropped instead of overwriting the new device's state.
  const generation = useRef(0);

  // Status carries the cue that is playing, so the STOP button and the phone beat also appear
  // when the app connects in the middle of one. A test cue never sets cue_active; leave it be.
  const applyStatus = useCallback((next: Status) => {
    setStatus(next);
    setCue((current) => (next.cue ? toCue(next.cue) : current?.trigger === 'test' ? current : null));
  }, []);

  const refreshHistory = useCallback(async () => {
    const mine = generation.current;
    const [eventList, days] = await Promise.all([client.getEvents(), client.getSummary()]);
    if (generation.current !== mine) return;
    setEvents(eventList.events);
    setSummary(days);
  }, [client]);

  const sync = useCallback(async () => {
    const mine = generation.current;
    setConnection((current) => (current === 'online' ? current : 'connecting'));
    try {
      const [nextStatus, nextSettings] = await Promise.all([client.getStatus(), client.getSettings()]);
      if (generation.current !== mine) return;
      applyStatus(nextStatus);
      setSettings(nextSettings);
      setConnection('online');
      setError(null);
      client.syncTime().catch(() => {}); // the app owns real time; failure is not fatal
      await refreshHistory();
    } catch (problem) {
      if (generation.current !== mine) return;
      setConnection('offline');
      setError(describe(problem));
    }
  }, [client, applyStatus, refreshHistory]);

  // -- live channel ------------------------------------------------------
  useEffect(() => {
    generation.current += 1;
    let disposed = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    // A different device: nothing on screen belongs to it yet.
    setStatus(null);
    setSettings(null);
    setEvents([]);
    setSummary(null);
    setCue(null);

    const connect = () => {
      if (disposed || AppState.currentState === 'background') return;
      const ws = new WebSocket(client.wsUrl());
      socket = ws;

      // Every (re)connect re-reads everything: cues, settings and events may have changed while
      // the link was down.
      ws.onopen = () => {
        if (!disposed && socket === ws) sync();
      };

      ws.onmessage = (raw) => {
        if (disposed || socket !== ws) return;
        let message: LiveMessage;
        try {
          message = JSON.parse(raw.data as string);
        } catch {
          return;
        }
        if (message.type === 'status') {
          applyStatus(message);
        } else if (message.type === 'cue_started') {
          setCue(toCue(message));
        } else if (message.type === 'cue_stopped') {
          setCue(null);
        } else if (message.type === 'event_created') {
          setEvents((current) => [message.event, ...current.filter((e) => e.id !== message.event.id)]);
          client.getSummary().then(setSummary).catch(() => {});
        }
      };

      // React Native fires `error` and then `close` for a failed connection, so only `close`
      // schedules the retry; handling both doubles the retries on every round.
      ws.onclose = () => {
        if (disposed || socket !== ws) return;
        socket = null;
        setConnection('offline');
        setCue(null); // the device takes a phone cue over on its buzzer when the phone goes away
        retry = setTimeout(connect, 2000);
      };
    };

    // In the background the phone's timers stop, so it cannot keep a beat. Closing the socket
    // tells the device nobody is listening, and it plays the cue on its own buzzer instead.
    const appState = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        if (!socket) connect();
      } else if (next === 'background') {
        if (retry) clearTimeout(retry);
        retry = null;
        const ws = socket;
        socket = null;
        ws?.close();
        setCue(null);
      }
    });

    connect();

    return () => {
      disposed = true;
      appState.remove();
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [client, sync, applyStatus]);

  // -- polling while the socket is down -----------------------------------
  // Covers a device that boots after the app: REST starts answering, then everything syncs.
  useEffect(() => {
    if (connection === 'online') return;
    const timer = setInterval(() => {
      client
        .getStatus()
        .then(() => sync())
        .catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [connection, client, sync]);

  // -- actions -----------------------------------------------------------
  const attempt = useCallback(async <T,>(action: () => Promise<T>): Promise<T | null> => {
    try {
      const result = await action();
      setError(null);
      return result;
    } catch (problem) {
      setError(describe(problem));
      return null;
    }
  }, []);

  // Returns the stopped event's id, or null when nothing was playing.
  const stopCue = useCallback(
    async (feedback?: Feedback) => {
      setCue(null); // silence the phone first: it must stop even if the device cannot be reached
      const result = await attempt(() => client.stopCue(feedback));
      if (!result?.stopped) return null;
      refreshHistory().catch(() => {});
      return result.event_id;
    },
    [client, attempt, refreshHistory],
  );

  const setFeedback = useCallback(
    async (id: number, feedback: Feedback | null) => {
      const updated = await attempt(() => client.setFeedback(id, feedback));
      if (!updated) return;
      setEvents((current) => current.map((e) => (e.id === id ? updated : e)));
      client.getSummary().then(setSummary).catch(() => {});
    },
    [client, attempt],
  );

  const updateSettings = useCallback(
    async (patch: Partial<Settings>) => {
      const next = await attempt(() => client.patchSettings(patch));
      if (next) setSettings(next);
    },
    [client, attempt],
  );

  const act = useCallback(
    async (action: () => Promise<Status>) => {
      const next = await attempt(action);
      if (next) applyStatus(next);
    },
    [attempt, applyStatus],
  );
  const startBeat = useCallback((seconds: number) => act(() => client.startCue(seconds)), [act, client]);
  const pause = useCallback((minutes: number) => act(() => client.pause(minutes)), [act, client]);
  const resume = useCallback(() => act(() => client.resume()), [act, client]);
  const testCue = useCallback(() => attempt(() => client.testCue()), [attempt, client]);

  // Changing the address re-runs the live effect, which syncs; the same address just re-syncs.
  const connectTo = useCallback(
    (text: string) => {
      const next = normaliseHost(text);
      if (!next) return setError('Enter the device address, for example 10.0.0.5:8000');
      if (next === host) sync();
      else setHost(next);
    },
    [host, sync],
  );

  return {
    host,
    connectTo,
    connection,
    status,
    settings,
    events,
    summary,
    cue,
    error,
    stopCue,
    setFeedback,
    updateSettings,
    startBeat,
    pause,
    resume,
    testCue,
  };
}
