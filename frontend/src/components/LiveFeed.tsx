import { useEffect, useRef } from "react";
import type { RunEvent } from "../hooks/useRunEvents";

function describe(event: RunEvent): string {
  const d = event.data;
  switch (event.type) {
    case "log":
      return String(d.message ?? "");
    case "step":
      return `step finished: ${String(d.node)}`;
    case "approval_required":
      return `waiting for you: ${String(d.kind)} approval`;
    case "approval_decided":
      return `decision: ${String(d.decision)}`;
    case "finished":
      return `run finished: ${String(d.status)}${d.stop_reason ? ` (${String(d.stop_reason)})` : ""}`;
    default:
      return event.type;
  }
}

/** The run's event stream as a scrolling log. Steps are shown in the agent cards, so
 * only progress lines, approvals and the end are listed here. */
export function LiveFeed({ events, connected }: { events: RunEvent[]; connected: boolean }) {
  const end = useRef<HTMLLIElement>(null);
  const shown = events.filter((e) => e.type !== "step" && e.type !== "status");
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [shown.length]);

  return (
    <section className="panel feed" aria-label="Live progress">
      <header className="feed-header">
        <h2>Live progress</h2>
        <span className={`dot ${connected ? "working" : "waiting"}`} aria-hidden="true" />
        <span className="muted">{connected ? "connected" : "not connected"}</span>
      </header>
      <ol>
        {shown.map((event) => (
          <li key={event.id} className={`feed-${event.type}`}>
            {describe(event)}
          </li>
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>
    </section>
  );
}
