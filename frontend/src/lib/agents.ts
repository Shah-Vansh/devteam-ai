import type { RunStatus, Step } from "../api/types";

export type AgentName = "planner" | "developer" | "reviewer" | "tester";
export const AGENTS: AgentName[] = ["planner", "developer", "reviewer", "tester"];

export const AGENT_LABEL: Record<AgentName, string> = {
  planner: "Planner",
  developer: "Developer",
  reviewer: "Reviewer",
  tester: "Tester",
};

/** Which agent does the work in each workflow node. Human pauses and the commit are
 * not agent work and are shown elsewhere. */
export const NODE_AGENT: Record<string, AgentName | undefined> = {
  plan: "planner",
  clarify: "planner",
  develop: "developer",
  revise: "developer",
  fix_code: "developer",
  review: "reviewer",
  write_tests: "tester",
  run_tests: "tester",
  triage: "tester",
  fix_tests: "tester",
};

/** Progress lines start with the speaker, e.g. "reviewer: round 2". */
const LOG_PREFIX: Record<string, AgentName> = {
  "planner:": "planner",
  "developer:": "developer",
  "reviewer:": "reviewer",
  "tester:": "tester",
  "executor": "tester",
};

export function agentFromLog(message: string): AgentName | undefined {
  const lower = message.toLowerCase();
  for (const [prefix, agent] of Object.entries(LOG_PREFIX)) {
    if (lower.startsWith(prefix)) return agent;
  }
  return undefined;
}

export type CardState = "waiting" | "working" | "done" | "failed";

export interface AgentCard {
  agent: AgentName;
  state: CardState;
  rounds: number;
  summary: string;
}

const FAILED_BY: Partial<Record<RunStatus, AgentName>> = {
  FAILED_REVIEW: "reviewer",
  FAILED_TESTS: "tester",
};

/** Build the four agent cards from finished steps, the latest progress line and the
 * run status. */
export function agentCards(
  steps: Pick<Step, "agent" | "summary">[],
  status: RunStatus,
  lastLog?: string,
): AgentCard[] {
  const active = status === "RUNNING" && lastLog ? agentFromLog(lastLog) : undefined;
  return AGENTS.map((agent) => {
    const own = steps.filter((s) => NODE_AGENT[s.agent] === agent);
    let state: CardState = own.length ? "done" : "waiting";
    if (agent === active) state = "working";
    if (FAILED_BY[status] === agent) state = "failed";
    return {
      agent,
      state,
      rounds: own.length,
      summary: agent === active && lastLog ? lastLog : (own.at(-1)?.summary ?? ""),
    };
  });
}

export const TERMINAL_STATUSES: RunStatus[] = [
  "SUCCESS",
  "NOT_COMMITTED",
  "FAILED_REVIEW",
  "FAILED_TESTS",
  "NOT_EXECUTED",
  "ERROR",
  "CANCELLED",
];

export function isFinished(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
