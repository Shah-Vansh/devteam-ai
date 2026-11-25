import type { ApprovalKind, RunStatus, Step } from "../api/types";

/** The stages shown in the pipeline, in order. Each groups one or more workflow nodes. */
export type StageId =
  | "plan"
  | "develop"
  | "review"
  | "tests"
  | "approve_run"
  | "sandbox"
  | "fix"
  | "approve_commit"
  | "commit";

export type StageKind = "agent" | "gate" | "system";
export type StageState = "pending" | "active" | "waiting" | "done" | "failed" | "skipped";

export interface StageDef {
  id: StageId;
  label: string;
  kind: StageKind;
  actor: string; // who does the work
  nodes: string[]; // workflow nodes that belong to this stage
}

export const STAGES: StageDef[] = [
  { id: "plan", label: "Plan", kind: "agent", actor: "Planner", nodes: ["plan", "clarify"] },
  { id: "develop", label: "Develop", kind: "agent", actor: "Developer", nodes: ["develop", "revise"] },
  { id: "review", label: "Review", kind: "agent", actor: "Reviewer", nodes: ["review"] },
  { id: "tests", label: "Write tests", kind: "agent", actor: "Tester", nodes: ["write_tests"] },
  { id: "approve_run", label: "Approve run", kind: "gate", actor: "You", nodes: ["approve"] },
  { id: "sandbox", label: "Sandbox", kind: "system", actor: "E2B microVM", nodes: ["run_tests"] },
  { id: "fix", label: "Fix loop", kind: "agent", actor: "Tester + Developer", nodes: ["triage", "fix_code", "fix_tests"] },
  { id: "approve_commit", label: "Approve commit", kind: "gate", actor: "You", nodes: ["prepare_commit", "approve_commit"] },
  { id: "commit", label: "Commit", kind: "system", actor: "Git MCP", nodes: ["commit"] },
];

const NODE_STAGE = new Map<string, StageId>(
  STAGES.flatMap((stage) => stage.nodes.map((node) => [node, stage.id] as const)),
);

export function stageOfNode(node: string): StageId | undefined {
  return NODE_STAGE.get(node);
}

/** Progress lines name what is happening now, e.g. "developer: fix round 1". */
const LOG_STAGE: [RegExp, StageId][] = [
  [/^planner:/i, "plan"],
  [/^re-planning/i, "plan"],
  [/^developer: (writing|revision)/i, "develop"],
  [/^developer: fix round/i, "fix"],
  [/^reviewer:/i, "review"],
  [/^tester: writing tests/i, "tests"],
  [/^executor/i, "sandbox"],
  [/^tester: (triaging|fixing)/i, "fix"],
];

export function stageFromLog(message: string): StageId | undefined {
  return LOG_STAGE.find(([pattern]) => pattern.test(message))?.[1];
}

const GATE_OF_APPROVAL: Record<ApprovalKind, StageId> = {
  clarify: "plan",
  execute: "approve_run",
  commit: "approve_commit",
};

/** A stop reason starts with the workflow node that gave up, e.g. "write_tests: no usable
 * answer: ...". That node's stage is where the run failed. */
export function stageFromReason(reason: string | null | undefined): StageId | undefined {
  const node = reason?.match(/^([a-z_]+):/)?.[1];
  return node ? stageOfNode(node) : undefined;
}

/** Which stage a terminal status points at by default, and what that stage shows. */
const END_STAGE: Partial<Record<RunStatus, [StageId, StageState]>> = {
  FAILED_REVIEW: ["review", "failed"],
  FAILED_TESTS: ["fix", "failed"],
  NOT_EXECUTED: ["approve_run", "skipped"],
  NOT_COMMITTED: ["approve_commit", "skipped"],
};

export interface StageView extends StageDef {
  state: StageState;
  runs: number; // finished steps in this stage (loops show more than one)
}

export interface PipelineInput {
  status: RunStatus;
  steps: Pick<Step, "agent">[];
  lastLog?: string;
  pendingKind?: ApprovalKind;
  error?: string | null; // the run's stop reason
}

const FAILED_END = new Set<RunStatus>(["FAILED_REVIEW", "FAILED_TESTS", "ERROR", "CANCELLED"]);

export function buildPipeline({
  status,
  steps,
  lastLog,
  pendingKind,
  error,
}: PipelineInput): StageView[] {
  const runs = new Map<StageId, number>();
  for (const step of steps) {
    const stage = stageOfNode(step.agent);
    if (stage) runs.set(stage, (runs.get(stage) ?? 0) + 1);
  }
  const lastStage = [...steps].reverse().map((s) => stageOfNode(s.agent)).find(Boolean);

  let current: [StageId, StageState] | undefined;
  if (status === "PAUSED" && pendingKind) {
    current = [GATE_OF_APPROVAL[pendingKind], "waiting"];
  } else if (status === "RUNNING") {
    const fromLog = lastLog ? stageFromLog(lastLog) : undefined;
    current = [fromLog ?? lastStage ?? "plan", "active"];
  } else if (FAILED_END.has(status) && stageFromReason(error)) {
    current = [stageFromReason(error)!, "failed"];
  } else if (END_STAGE[status]) {
    current = END_STAGE[status];
  } else if (status === "ERROR" || status === "CANCELLED") {
    const fromLog = lastLog ? stageFromLog(lastLog) : undefined;
    current = [fromLog ?? lastStage ?? "plan", "failed"];
  }

  const currentIndex = current ? STAGES.findIndex((s) => s.id === current[0]) : -1;
  // A run that has ended never reaches the stages it did not get to.
  const ended = status !== "RUNNING" && status !== "PAUSED";

  return STAGES.map((stage, index) => {
    const count = runs.get(stage.id) ?? 0;
    let state: StageState = count > 0 ? "done" : "pending";
    if (current && stage.id === current[0]) {
      state = current[1];
    } else if (stage.id === "fix" && count === 0) {
      // The fix loop only runs when tests fail; once the run moves past it, it was skipped.
      const passedIt = ended || (currentIndex > index && currentIndex !== -1);
      if (passedIt) state = "skipped";
    } else if (ended && state === "pending") {
      state = "skipped";
    }
    return { ...stage, state, runs: count };
  });
}

/** The connection into a stage animates while that stage is working. */
export function edgeState(stages: StageView[], index: number): "done" | "active" | "pending" {
  const target = stages[index];
  if (!target) return "pending";
  if (target.state === "active" || target.state === "waiting") return "active";
  // A stage the run never reached (pending, or skipped after it ended) is not on the
  // travelled track.
  return target.state === "pending" || target.state === "skipped" ? "pending" : "done";
}
