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

type Cue = { eventId: number | null; output: string; tempoBpm: number; trigger: string };

const toCue = (cue: LiveCue): Cue => ({
  eventId: cue.event_id,
  output: cue.output,
  tempoBpm: cue.tempo_bpm,
  trigger: cue.trigger,
});
const describe = (problem: unknown) => (problem instanceof Error ? problem.message : String(problem));

// The device sends a status message at least every 5 s. A board that loses power or walks out of range
// sends no goodbye, and the socket can take minutes to notice; silence this long means the link is gone.
const SILENCE_LIMIT_MS = 12_000;

// "10.0.0.5:8000", whatever was pasted: no scheme, no path.
const normaliseHost = (text: string) =>
  text.trim().replace(/^[a-z]+:\/\//i, '').replace(/\/.*$/, '');

export function useDevice(initialHost: string | null = null) {
  const [host, setHost] = useState(initialHost ?? DEFAULT_HOST);
  const [connection, setConnection] = useState<Connection>('connecting');
  const [status, setStatus] = useState<Status | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [events, setEvents] = useState<FogEvent[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [cue, setCue] = useState<Cue | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The automatic cue the wearer last stopped, which STOP marked a false alarm. Kept until they answer or
  // the next cue starts, with no countdown: nothing here has to be done against the clock.
  const [stoppedEventId, setStoppedEventId] = useState<number | null>(null);

  const client = useMemo(() => new DeviceClient(host), [host]);

  // Bumped whenever the device address changes, so an answer from the old address that arrives
  // late is dropped instead of overwriting the new device's state.
  const generation = useRef(0);

  // The event the wearer pressed STOP on. A status message already on its way can still name it as
  // playing; without this the phone would take the beat up again for a moment.
  const stoppedEvent = useRef<number | null>(null);

  // Status carries the cue that is playing, so the STOP button and the phone beat also appear
  // when the app connects in the middle of one. A test cue never sets cue_active; leave it be.
  const applyStatus = useCallback((next: Status) => {
    setStatus(next);
    const playing = next.cue && next.cue.event_id !== stoppedEvent.current ? next.cue : null;
    setCue((current) => (playing ? toCue(playing) : current?.trigger === 'test' ? current : null));
  }, []);

  const refreshSummary = useCallback(() => {
    const mine = generation.current;
    client
      .getSummary()
      .then((days) => {
        if (generation.current === mine) setSummary(days);
      })
      .catch(() => {});
  }, [client]);

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
    let lastHeard = Date.now();

    // A different device: nothing on screen belongs to it yet, and it has not answered.
    setConnection('connecting');
    setError(null);
    setStatus(null);
    setSettings(null);
    setEvents([]);
    setSummary(null);
    setCue(null);
    setStoppedEventId(null);

    // The link is gone: by a close, or by silence. Only ever for the socket that is current.
    const lost = (ws: WebSocket) => {
      if (disposed || socket !== ws) return;
      socket = null;
      ws.close();
      setConnection('offline');
      setCue(null); // the device takes a phone cue over on its own output when the phone goes away
      retry = setTimeout(connect, 2000);
    };

    // One socket at a time. A second one would never be closed, and the device would go on believing
    // a phone is listening after this app has gone to the background.
    const connect = () => {
      if (retry) clearTimeout(retry);
      retry = null;
      if (disposed || socket || AppState.currentState === 'background') return;
      const ws = new WebSocket(client.wsUrl());
      socket = ws;
      lastHeard = Date.now();

      // Every (re)connect re-reads everything: cues, settings and events may have changed while
      // the link was down.
      ws.onopen = () => {
        if (!disposed && socket === ws) sync();
      };

      ws.onmessage = (raw) => {
        if (disposed || socket !== ws) return;
        lastHeard = Date.now();
        let message: LiveMessage;
        try {
          message = JSON.parse(raw.data as string);
        } catch {
          return;
        }
        if (message.type === 'status') {
          applyStatus(message);
        } else if (message.type === 'cue_started') {
          // "Test the cue" pressed during a real cue must not replace it, nor end it 2 s later.
          setCue((current) => (current && current.trigger !== 'test' && message.trigger === 'test' ? current : toCue(message)));
          if (message.trigger !== 'test') setStoppedEventId(null);
        } else if (message.type === 'cue_stopped') {
          setCue((current) => (current && current.eventId === message.event_id ? null : current));
        } else if (message.type === 'event_created') {
          setEvents((current) => [message.event, ...current.filter((e) => e.id !== message.event.id)]);
          refreshSummary();
        }
      };

      // React Native fires `error` and then `close` for a failed connection, so only `close`
      // schedules the retry; handling both doubles the retries on every round.
      ws.onclose = () => lost(ws);
    };

    const watchdog = setInterval(() => {
      if (socket && Date.now() - lastHeard > SILENCE_LIMIT_MS) lost(socket);
    }, 4000);

    // In the background the phone's timers stop, so it cannot keep a beat. Closing the socket
    // tells the device nobody is listening, and it plays the cue on its own buzzer instead.
    const appState = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        connect();
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
      clearInterval(watchdog);
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [client, sync, applyStatus, refreshSummary]);

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
      // Silence the phone first: it must stop even if the device cannot be reached.
      setCue((current) => {
        if (current?.eventId != null) stoppedEvent.current = current.eventId;
        return null;
      });
      const result = await attempt(() => client.stopCue(feedback));
      if (!result?.stopped) return null;
      refreshHistory().catch(() => {});
      if (feedback === 'false_alarm') setStoppedEventId(result.event_id);
      return result.event_id;
    },
    [client, attempt, refreshHistory],
  );

  // True when the device recorded the verdict.
  const setFeedback = useCallback(
    async (id: number, feedback: Feedback | null) => {
      const updated = await attempt(() => client.setFeedback(id, feedback));
      if (!updated) return false;
      setEvents((current) => current.map((e) => (e.id === id ? updated : e)));
      refreshSummary();
      return true;
    },
    [client, attempt, refreshSummary],
  );

  const updateSettings = useCallback(
    async (patch: Partial<Settings>) => {
      const next = await attempt(() => client.patchSettings(patch));
      if (next) setSettings(next);
    },
    [client, attempt],
  );

  // "No, I really was stuck": take back the false-alarm mark STOP put on the event.
  const confirmRealFreeze = useCallback(async () => {
    if (stoppedEventId != null && (await setFeedback(stoppedEventId, 'real'))) setStoppedEventId(null);
  }, [stoppedEventId, setFeedback]);
  const dismissStopped = useCallback(() => setStoppedEventId(null), []);

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
    stoppedEventId,
    confirmRealFreeze,
    dismissStopped,
    setFeedback,
    updateSettings,
    startBeat,
    pause,
    resume,
    testCue,
  };
}
