import { api } from "../api/client";
import type { Decision } from "../api/types";
import { AgentCards } from "../components/AgentCards";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { LiveFeed } from "../components/LiveFeed";
import { agentCards } from "../lib/agents";
import { useRunContext } from "./RunLayout";

export function RunLivePage() {
  const { run, report, events, connected, reload } = useRunContext();
  const lastLog = [...events].reverse().find((e) => e.type === "log")?.data.message;
  const cards = agentCards(report?.steps ?? [], run.status, lastLog ? String(lastLog) : undefined);

  async function decide(decision: Decision) {
    if (!run.pending_approval) return;
    await api.decide(run.pending_approval.id, decision);
    reload();
  }

  return (
    <div className="live">
      <AgentCards cards={cards} />
      {run.status === "PAUSED" && run.pending_approval && (
        <ApprovalPanel
          key={run.pending_approval.id}
          approval={run.pending_approval}
          onDecide={decide}
        />
      )}
      {run.commit_sha && (
        <p className="panel success">
          Committed <code>{run.commit_sha.slice(0, 10)}</code> in <code>{run.workspace}</code>.
        </p>
      )}
      <LiveFeed events={events} connected={connected} />
    </div>
  );
}
