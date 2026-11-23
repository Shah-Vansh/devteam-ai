import { useEffect, useRef } from "react";
import type { RunEvent } from "../hooks/useRunEvents";
import { agentFromLog } from "../lib/agents";
import { logTone } from "../lib/logline";

interface Line {
  tag: string;
  tone: string;
  text: string;
  className?: string;
}

function describe(event: RunEvent): Line {
  const d = event.data;
  switch (event.type) {
    case "log": {
      const message = String(d.message ?? "");
      const agent = agentFromLog(message);
      if (message.toLowerCase().startsWith("executor")) {
        return { tag: "sandbox", tone: "sandbox", text: message.replace(/^executor \(\w+\): /i, "") };
      }
      if (agent) {
        return { tag: agent, tone: agent, text: message.replace(/^\w+: /, "") };
      }
      const tone = logTone(message);
      if (tone === "fail") return { tag: "error", tone: "fail", text: message };
      if (tone === "pass") return { tag: "passed", tone: "done", text: message };
      return { tag: "info", tone: "", text: message };
    }
    case "approval_required":
      return { tag: "gate", tone: "gate", text: `waiting for you: ${String(d.kind)} approval`, className: "gate" };
    case "approval_decided":
      return { tag: "you", tone: "gate", text: `decision: ${String(d.decision)}`, className: "gate" };
    case "finished": {
      const ok = d.status === "SUCCESS";
      const reason = d.stop_reason ? ` (${String(d.stop_reason)})` : "";
      return {
        tag: ok ? "done" : "end",
        tone: ok ? "done" : "fail",
        text: `run finished: ${String(d.status)}${reason}`,
        className: "end",
      };
    }
    default:
      return { tag: event.type, tone: "", text: "" };
  }
}

const time = (date: Date) => date.toLocaleTimeString([], { hour12: false });

/** The run's event stream as a terminal: time, who, what. Steps are shown in the pipeline,
 * so only progress lines, approvals and the end are listed. */
export function LiveFeed(props: { events: RunEvent[]; connected: boolean; title?: string }) {
  const { events, connected, title = "run.log" } = props;
  const list = useRef<HTMLOListElement>(null);
  const shown = events.filter((e) => e.type !== "step" && e.type !== "status");
  const live = connected && shown.at(-1)?.type !== "finished";

  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  return (
    <section className="terminal" aria-label="Live progress">
      <header className="terminal-bar">
        <span className="lights" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="terminal-title">{title}</span>
        <span className="terminal-status">
          <span className={`dot ${connected ? "on" : ""}`} aria-hidden="true" />
          {connected ? "connected" : "not connected"}
        </span>
      </header>
      <ol ref={list}>
        {shown.length === 0 && (
          <li>
            <span className="t-time" />
            <span className="t-tag">info</span>
            <span className="t-msg">waiting for events…</span>
          </li>
        )}
        {shown.map((event, i) => {
          const line = describe(event);
          const last = i === shown.length - 1;
          return (
            <li key={event.id} className={`feed-${event.type} ${last && live ? "cursor-line" : ""}`}>
              <span className="t-time">{time(event.receivedAt)}</span>
              <span className={`t-tag ${line.tone}`}>{line.tag}</span>
              <span className={`t-msg ${line.className ?? ""}`}>{line.text}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
