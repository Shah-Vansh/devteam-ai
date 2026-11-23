import { api } from "../api/client";
import type { Decision } from "../api/types";
import { AgentCards } from "../components/AgentCards";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { Icon } from "../components/icons";
import { LiveFeed } from "../components/LiveFeed";
import { TryApi } from "../components/TryApi";
import { isDemo } from "../demo/demo";
import { agentCards, isFinished } from "../lib/agents";
import { useRunContext } from "./RunLayout";

export function RunLivePage() {
  const { run, report, events, connected, lastLog, reload } = useRunContext();
  const cards = agentCards(report?.steps ?? [], run.status, lastLog);

  async function decide(decision: Decision) {
    if (!run.pending_approval) return;
    await api.decide(run.pending_approval.id, decision);
    reload();
  }

  return (
    <div className="live">
      <aside aria-label="Agents">
        <AgentCards cards={cards} />
      </aside>
      <div className="live-main">
        {run.status === "PAUSED" && run.pending_approval && (
          <ApprovalPanel
            key={run.pending_approval.id}
            approval={run.pending_approval}
            onDecide={decide}
          />
        )}
        {run.commit_sha && (
          <div className="success-card">
            <span className="gate-icon">
              <Icon name="commit" />
            </span>
            <p>
              Committed <code>{run.commit_sha.slice(0, 10)}</code> in <code>{run.workspace}</code>.
            </p>
          </div>
        )}
        {run.test_status === "PASSED" && isFinished(run.status) && !isDemo(run.id) && (
          <TryApi runId={run.id} />
        )}
        <LiveFeed events={events} connected={connected} title={`${run.id} — run.log`} />
      </div>
    </div>
  );
}
