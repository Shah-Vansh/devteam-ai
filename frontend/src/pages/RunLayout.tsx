import { useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Report, Run } from "../api/types";
import { ErrorBox, Loading, Stat, StatusBadge } from "../components/common";
import { useAsync } from "../hooks/useAsync";
import { type RunEvent, useRunEvents } from "../hooks/useRunEvents";
import { formatTokens, isFinished } from "../lib/agents";

export interface RunContext {
  run: Run;
  report: Report | undefined;
  events: RunEvent[];
  connected: boolean;
  reload: () => void;
}

export const useRunContext = () => useOutletContext<RunContext>();

const REFRESH_ON = new Set(["step", "approval_required", "approval_decided", "finished"]);

/** Shared frame of the run screens: one event stream and one copy of the run's data for
 * all tabs, so switching tabs neither reconnects nor reloads everything. */
export function RunLayout() {
  const { runId = "" } = useParams();
  const run = useAsync(() => api.getRun(runId), [runId]);
  const report = useAsync(() => api.report(runId), [runId]);
  const [cancelError, setCancelError] = useState<string>();

  const reload = () => {
    run.reload();
    report.reload();
  };
  const { events, connected } = useRunEvents(runId, (event) => {
    if (REFRESH_ON.has(event.type)) reload();
  });

  if (run.error && !run.data) return <ErrorBox error={run.error} />;
  if (!run.data) return <Loading what="Loading run" />;
  const current = run.data;

  async function cancel() {
    setCancelError(undefined);
    try {
      await api.cancelRun(current.id);
      reload();
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="run">
      <header className="run-header panel">
        <div className="run-title">
          <Link to="/" className="muted">
            ← Projects
          </Link>
          <h1>
            Run <code>{current.id}</code>
          </h1>
          <StatusBadge status={current.status} />
          {!isFinished(current.status) && (
            <button type="button" className="danger small" onClick={cancel}>
              Cancel run
            </button>
          )}
        </div>
        {current.error && current.status !== "SUCCESS" && (
          <p className="error">{current.error}</p>
        )}
        {cancelError && (
          <p role="alert" className="error">
            {cancelError}
          </p>
        )}
        <div className="stats">
          <Stat label="review rounds" value={current.review_rounds} />
          <Stat label="fix rounds" value={current.fix_rounds} />
          <Stat label="LLM calls" value={current.llm_calls} />
          <Stat
            label="tokens in / out"
            value={`${formatTokens(current.input_tokens)} / ${formatTokens(current.output_tokens)}`}
          />
          <Stat label="model" value={current.model ?? "—"} />
        </div>
        <nav className="tabs" aria-label="Run views">
          <NavLink end to={`/runs/${current.id}`}>
            Live
          </NavLink>
          <NavLink to={`/runs/${current.id}/workspace`}>Workspace</NavLink>
          <NavLink to={`/runs/${current.id}/report`}>Report</NavLink>
        </nav>
      </header>
      <Outlet
        context={
          { run: current, report: report.data, events, connected, reload } satisfies RunContext
        }
      />
    </div>
  );
}
