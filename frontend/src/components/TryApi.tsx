import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Preview } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { Icon } from "./icons";

function remaining(expiresAt: string | null, now: number): string {
  if (!expiresAt) return "";
  const seconds = Math.max(0, Math.round((new Date(expiresAt).getTime() - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** "Try the API": start the generated app in a sandbox for a few minutes and open its
 * interactive docs. Shown only for runs whose tests passed, when a sandbox is configured. */
export function TryApi({ runId }: { runId: string }) {
  const health = useAsync(() => api.health(), []);
  const initial = useAsync(() => api.preview(runId), [runId]);
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [now, setNow] = useState(() => Date.now());

  const current = preview ?? initial.data;
  const running = current?.status === "running" && current.url;

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    // The sandbox deletes itself when its time is up; show that without a reload.
    if (running && current.expires_at && new Date(current.expires_at).getTime() <= now) {
      setPreview({ status: "stopped", url: null, expires_at: null });
    }
  }, [running, current, now]);

  if (!health.data?.preview_available) return null;

  async function start() {
    setBusy(true);
    setError(undefined);
    try {
      setPreview(await api.startPreview(runId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      setPreview(await api.stopPreview(runId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel try-api" aria-label="Try the API">
      <div className="try-api-head">
        <span className="gate-icon">
          <Icon name="play" />
        </span>
        <div>
          <h2>Try the API</h2>
          <p className="muted">
            Runs the generated app in a fresh E2B sandbox for 10 minutes, with its outbound
            internet off. Its interactive docs open in a new tab.
          </p>
        </div>
      </div>
      {running ? (
        <div className="try-api-live">
          <span className="dot on" />
          <a className="button primary" href={`${current.url}/docs`} target="_blank" rel="noreferrer">
            <Icon name="external" width={14} height={14} />
            Open the API docs
          </a>
          <code className="try-api-url">{current.url}</code>
          <span className="muted small" aria-label="Time left">
            stops in {remaining(current.expires_at, now)}
          </span>
          <button type="button" className="small" onClick={stop} disabled={busy}>
            <Icon name="stop" width={12} height={12} />
            Stop
          </button>
        </div>
      ) : (
        <div className="try-api-live">
          <button type="button" className="primary" onClick={start} disabled={busy}>
            <Icon name="play" width={14} height={14} />
            {busy ? "Starting the app… (about 30–60 s)" : "Start the app"}
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="run-error">
          {error}
        </p>
      )}
    </section>
  );
}
