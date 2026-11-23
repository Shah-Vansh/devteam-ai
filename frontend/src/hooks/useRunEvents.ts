import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { demoReplay, isDemo } from "../demo/demo";

export const EVENT_TYPES = [
  "log",
  "step",
  "status",
  "approval_required",
  "approval_decided",
  "finished",
] as const;
export type RunEventType = (typeof EVENT_TYPES)[number];

export interface RunEvent {
  id: string;
  type: RunEventType;
  data: Record<string, unknown>;
  receivedAt: Date; // when the browser got it (replayed history shows the replay time)
}

/**
 * Follow a run's Server-Sent Events stream.
 *
 * The browser's EventSource reconnects on its own and sends Last-Event-ID, so the server
 * continues where it stopped. The stream is closed after `finished`: otherwise EventSource
 * would reconnect and receive the finished run again.
 */
export function useRunEvents(runId: string, onEvent?: (event: RunEvent) => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [finished, setFinished] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    setEvents([]);
    setFinished(false);
    if (isDemo(runId)) return followDemo();
    const source = new EventSource(api.eventsUrl(runId));
    const seen = new Set<string>(); // ids already shown (replays after a reconnect)
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    const handle = (type: RunEventType) => (message: MessageEvent<string>) => {
      if (message.lastEventId && seen.has(message.lastEventId)) return;
      if (message.lastEventId) seen.add(message.lastEventId);
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(message.data) as Record<string, unknown>;
      } catch {
        data = { raw: message.data };
      }
      // The server stamps each event when it happened ("at"); a replayed history keeps
      // its real times. Events without a stamp (database snapshots) use arrival time.
      const at = typeof data.at === "string" ? new Date(data.at) : new Date();
      const event: RunEvent = {
        id: message.lastEventId || `${type}-${seen.size}`,
        type,
        data,
        receivedAt: Number.isNaN(at.getTime()) ? new Date() : at,
      };
      setEvents((previous) => [...previous, event]);
      onEventRef.current?.(event);
      if (type === "finished") {
        setFinished(true);
        setConnected(false);
        source.close();
      }
    };
    const listeners = EVENT_TYPES.map((type) => [type, handle(type)] as const);
    for (const [type, listener] of listeners) source.addEventListener(type, listener);
    return () => {
      for (const [type, listener] of listeners) source.removeEventListener(type, listener);
      source.close();
    };

    /** The demo run: events come from the in-browser replay instead of the server. */
    function followDemo() {
      setConnected(true);
      return demoReplay.subscribe(
        (item) => {
          const at = new Date(String(item.data.at));
          const event: RunEvent = {
            id: item.id,
            type: item.type as RunEventType,
            data: item.data,
            receivedAt: Number.isNaN(at.getTime()) ? new Date() : at,
          };
          setEvents((previous) => [...previous, event]);
          onEventRef.current?.(event);
          if (item.type === "finished") {
            setFinished(true);
            setConnected(false);
          }
        },
        () => {
          setEvents([]);
          setFinished(false);
          setConnected(true);
        },
      );
    }
  }, [runId]);

  return { events, connected, finished };
}
