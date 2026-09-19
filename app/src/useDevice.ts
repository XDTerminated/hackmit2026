// One hook owning the connection to the device: initial sync over REST, live updates
// over the WebSocket, and reconnection when the link drops. Falls back to polling
// GET /status so a dead socket costs liveness, never correctness.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  DeviceClient,
  DEFAULT_HOST,
  FogEvent,
  LiveMessage,
  Settings,
  Status,
  Summary,
} from './api';

export type Connection = 'connecting' | 'online' | 'offline';

export type Cue = { eventId: number | null; output: string; tempoBpm: number; trigger: string };

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
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshHistory = useCallback(async () => {
    const [eventList, days] = await Promise.all([client.getEvents(), client.getSummary(14)]);
    setEvents(eventList.events);
    setSummary(days);
  }, [client]);

  const sync = useCallback(async () => {
    setConnection((current) => (current === 'online' ? current : 'connecting'));
    try {
      const [nextStatus, nextSettings] = await Promise.all([
        client.getStatus(),
        client.getSettings(),
      ]);
      setStatus(nextStatus);
      setSettings(nextSettings);
      setConnection('online');
      setError(null);
      client.syncTime().catch(() => {}); // the app owns real time; failure is not fatal
      await refreshHistory();
    } catch (problem) {
      setConnection('offline');
      setError(problem instanceof Error ? problem.message : String(problem));
    }
  }, [client, refreshHistory]);

  // -- live channel ------------------------------------------------------
  useEffect(() => {
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(client.wsUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        if (!disposed) setConnection('online');
      };

      socket.onmessage = (raw) => {
        let message: LiveMessage;
        try {
          message = JSON.parse(raw.data as string);
        } catch {
          return;
        }
        if (message.type === 'status') {
          const { type, ...rest } = message as { type: string } & Status;
          setStatus(rest);
          if (!rest.cue_active) setCue(null);
        } else if (message.type === 'cue_started') {
          setCue({
            eventId: message.event_id,
            output: message.output,
            tempoBpm: message.tempo_bpm,
            trigger: message.trigger,
          });
        } else if (message.type === 'cue_stopped') {
          setCue(null);
        } else if (message.type === 'event_created') {
          setEvents((current) => [message.event, ...current.filter((e) => e.id !== message.event.id)]);
          client.getSummary(14).then(setSummary).catch(() => {});
        }
      };

      const drop = () => {
        if (disposed) return;
        setConnection('offline');
        retryRef.current = setTimeout(connect, 2000);
      };
      socket.onerror = drop;
      socket.onclose = drop;
    };

    sync();
    connect();

    return () => {
      disposed = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      socketRef.current?.close();
    };
  }, [client, sync]);

  // -- polling fallback --------------------------------------------------
  useEffect(() => {
    if (connection === 'online') return;
    const timer = setInterval(() => {
      client
        .getStatus()
        .then((next) => {
          setStatus(next);
          setConnection('online');
        })
        .catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [connection, client]);

  // -- actions -----------------------------------------------------------
  const stopCue = useCallback(
    async (feedback?: 'false_alarm') => {
      const result = await client.stopCue(feedback);
      setCue(null);
      setTimeout(() => refreshHistory().catch(() => {}), 1200);
      return result.event_id;
    },
    [client, refreshHistory],
  );

  const setFeedback = useCallback(
    async (id: number, feedback: 'false_alarm' | 'real' | null) => {
      const updated = await client.setFeedback(id, feedback);
      setEvents((current) => current.map((e) => (e.id === id ? updated : e)));
      client.getSummary(14).then(setSummary).catch(() => {});
    },
    [client],
  );

  const updateSettings = useCallback(
    async (patch: Partial<Settings>) => {
      try {
        setSettings(await client.patchSettings(patch));
        setError(null);
      } catch (problem) {
        setError(problem instanceof Error ? problem.message : String(problem));
      }
    },
    [client],
  );

  return {
    host,
    setHost,
    client,
    connection,
    status,
    settings,
    events,
    summary,
    cue,
    error,
    sync,
    refreshHistory,
    stopCue,
    setFeedback,
    updateSettings,
  };
}
