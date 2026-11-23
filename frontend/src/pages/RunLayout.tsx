import { useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Report, Run } from "../api/types";
import { Icon } from "../components/icons";
import { ErrorBox, Loading, Stat, StatusBadge } from "../components/common";
import { Pipeline } from "../components/Pipeline";
import { useAsync } from "../hooks/useAsync";
import { type RunEvent, useRunEvents } from "../hooks/useRunEvents";
import { formatTokens, isFinished } from "../lib/agents";
import { buildPipeline } from "../lib/pipeline";

export interface RunContext {
  run: Run;
  report: Report | undefined;
  events: RunEvent[];
  connected: boolean;
  lastLog: string | undefined;
  reload: () => void;
}

export const useRunContext = () => useOutletContext<RunContext>();

const REFRESH_ON = new Set(["step", "approval_required", "approval_decided", "finished"]);

function duration(run: Run): string {
  const end = run.finished_at ? new Date(run.finished_at) : new Date();
  const seconds = Math.max(0, Math.round((end.getTime() - new Date(run.started_at).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

/** Shared frame of the run screens: header, pipeline, and one event stream and one copy of
 * the run's data for all tabs, so switching tabs neither reconnects nor reloads. */
export function RunLayout() {
  const { runId = "" } = useParams();
  const run = useAsync(() => api.getRun(runId), [runId]);
  const report = useAsync(() => api.report(runId), [runId]);
  const project = useAsync(
    () => (run.data ? api.getProject(run.data.project_id) : Promise.resolve(undefined)),
    [run.data?.project_id],
  );
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
  const lastLog = [...events].reverse().find((e) => e.type === "log")?.data.message as
    | string
    | undefined;
  const stages = buildPipeline({
    status: current.status,
    steps: report.data?.steps ?? [],
    lastLog,
    pendingKind: current.pending_approval?.kind,
  });

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
      <header className="panel run-header">
        <Link to="/" className="crumb">
          ← Projects
        </Link>
        <div className="run-title">
          <h1>
            {project.data?.name ?? "run"} <span className="dim">/</span> <code>{current.id}</code>
          </h1>
          <StatusBadge status={current.status} />
          <span className="spacer" />
          {!isFinished(current.status) && (
            <button type="button" className="danger small" onClick={cancel}>
              <Icon name="x" width={13} height={13} />
              Cancel run
            </button>
          )}
        </div>
        {project.data && <p className="run-requirement">❯ {project.data.requirement}</p>}
        {current.error && current.status !== "SUCCESS" && (
          <p className="run-error">{current.error}</p>
        )}
        {cancelError && (
          <p role="alert" className="run-error">
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
          <Stat label="elapsed" value={duration(current)} />
          <Stat label="model" value={current.model?.replace("openai/", "") ?? "—"} />
        </div>
        <nav className="tabs" aria-label="Run views">
          <NavLink end to={`/runs/${current.id}`}>
            <Icon name="activity" width={14} height={14} />
            Live
          </NavLink>
          <NavLink to={`/runs/${current.id}/workspace`}>
            <Icon name="code" width={14} height={14} />
            Workspace
          </NavLink>
          <NavLink to={`/runs/${current.id}/report`}>
            <Icon name="report" width={14} height={14} />
            Report
          </NavLink>
        </nav>
      </header>
      <Pipeline stages={stages} />
      <Outlet
        context={
          {
            run: current,
            report: report.data,
            events,
            connected,
            lastLog,
            reload,
          } satisfies RunContext
        }
      />
    </div>
  );
}
