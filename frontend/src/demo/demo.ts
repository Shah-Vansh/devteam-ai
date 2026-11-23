/**
 * Demo mode: a real recorded run (scripts/record_demo.py) replayed in the browser at
 * /runs/demo. No backend, API keys or tokens are needed; nothing is executed.
 *
 * The pages do not know they are showing a demo: `withDemo` answers the same API calls
 * the live run would get, from the recording, as far as the replay has progressed, and
 * `demoReplay` stands in for the run's event stream. The replay pauses at each approval
 * until the viewer approves, like a real run.
 */
import type {
  Approval,
  Decision,
  FileEntry,
  GitInfo,
  Preview,
  ProjectDetail,
  Report,
  Review,
  Run,
  TestRun,
} from "../api/types";
import recordingJson from "./recording.json";

export const DEMO_RUN_ID = "demo";
export const DEMO_PROJECT_ID = "prj_demo";

export const isDemo = (id: string | undefined) => id === DEMO_RUN_ID || id === DEMO_PROJECT_ID;

interface RecordedEvent {
  type: string;
  data: Record<string, unknown>;
}

interface Recording {
  project: { id: string; name: string; requirement: string; created_at: string };
  run: Run;
  report: Report;
  files: FileEntry[];
  contents: Record<string, string>;
  reviews: Review[];
  tests: TestRun[];
  git: GitInfo;
  approvals: Approval[];
  events: RecordedEvent[];
}

const recording = recordingJson as unknown as Recording;

export interface DemoEvent {
  id: string;
  type: string;
  data: Record<string, unknown>;
}

type Listener = (event: DemoEvent) => void;

/** Real gaps between events, shortened so the whole run plays in about half a minute. */
const MIN_GAP_MS = 300;
const MAX_GAP_MS = 1800;

function gap(index: number, events: RecordedEvent[]): number {
  if (index === 0) return 600;
  const at = (i: number) => Date.parse(String(events[i]?.data.at ?? ""));
  const real = at(index) - at(index - 1);
  return Number.isFinite(real) ? Math.min(MAX_GAP_MS, Math.max(MIN_GAP_MS, real / 8)) : 600;
}

export class DemoReplay {
  delivered: DemoEvent[] = [];
  waiting = false; // paused at an approval
  startedAt = new Date();
  finishedAt: Date | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private listeners = new Set<Listener>();
  private resetListeners = new Set<() => void>();

  constructor(
    readonly events: RecordedEvent[],
    private readonly schedule: (fn: () => void, ms: number) => ReturnType<typeof setTimeout> = (
      fn,
      ms,
    ) => setTimeout(fn, ms),
  ) {}

  get finished(): boolean {
    return this.finishedAt !== undefined;
  }

  /** Follow the replay: already delivered events first, then new ones as they come.
   * The replay starts with its first subscriber. */
  subscribe(listener: Listener, onReset?: () => void): () => void {
    for (const event of this.delivered) listener(event);
    this.listeners.add(listener);
    if (onReset) this.resetListeners.add(onReset);
    if (this.delivered.length === 0 && this.timer === undefined) {
      this.startedAt = new Date(); // the clock starts with the replay, not at page load
      this.next();
    }
    return () => {
      this.listeners.delete(listener);
      if (onReset) this.resetListeners.delete(onReset);
    };
  }

  restart(): void {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
    this.delivered = [];
    this.waiting = false;
    this.startedAt = new Date();
    this.finishedAt = undefined;
    for (const reset of this.resetListeners) reset();
    this.next();
  }

  /** The viewer approved the pending step: continue. */
  approve(): void {
    if (!this.waiting) return;
    this.waiting = false;
    this.next();
  }

  count(type: string): number {
    return this.delivered.filter((e) => e.type === type).length;
  }

  private next(): void {
    const index = this.delivered.length;
    if (index >= this.events.length || this.waiting) return;
    this.timer = this.schedule(() => {
      this.timer = undefined;
      this.deliver(index);
    }, gap(index, this.events));
  }

  private deliver(index: number): void {
    const recorded = this.events[index];
    if (!recorded) return;
    // Shown with the time it is replayed, like a run happening now.
    const event: DemoEvent = {
      id: String(index + 1),
      type: recorded.type,
      data: { ...recorded.data, at: new Date().toISOString() },
    };
    this.delivered.push(event);
    if (event.type === "finished") this.finishedAt = new Date();
    if (event.type === "approval_required") this.waiting = true;
    for (const listener of this.listeners) listener(event);
    this.next();
  }
}

export const demoReplay = new DemoReplay(recording.events);

// ---------- the API, answered from the recording ----------

function stepsDone() {
  return recording.report.steps.slice(0, demoReplay.count("step"));
}

function reached(node: string): boolean {
  return stepsDone().some((s) => s.agent === node);
}

const LLM_STEPS = new Set(["plan", "develop", "review", "write_tests", "revise", "triage"]);

function demoRun(): Run {
  const final = recording.run;
  const llmTotal = recording.report.steps.filter((s) => LLM_STEPS.has(s.agent)).length || 1;
  const share = demoReplay.finished
    ? 1
    : stepsDone().filter((s) => LLM_STEPS.has(s.agent)).length / llmTotal;
  const approvalIndex = demoReplay.count("approval_required") - 1;
  const pending =
    demoReplay.waiting && recording.approvals[approvalIndex]
      ? {
          ...recording.approvals[approvalIndex],
          run_id: DEMO_RUN_ID,
          status: "pending" as const,
          answer: null,
          decided_at: null,
        }
      : null;
  return {
    ...final,
    id: DEMO_RUN_ID,
    project_id: DEMO_PROJECT_ID,
    status: demoReplay.finished ? "SUCCESS" : pending ? "PAUSED" : "RUNNING",
    current_step: stepsDone().at(-1)?.agent ?? null,
    review_status: reached("review") ? final.review_status : null,
    test_status: reached("run_tests") ? final.test_status : null,
    workspace: reached("develop") ? final.workspace : null,
    llm_calls: Math.round(final.llm_calls * share),
    input_tokens: Math.round(final.input_tokens * share),
    output_tokens: Math.round(final.output_tokens * share),
    commit_sha: demoReplay.finished ? final.commit_sha : null,
    error: null,
    started_at: demoReplay.startedAt.toISOString(),
    finished_at: demoReplay.finishedAt?.toISOString() ?? null,
    pending_approval: pending,
  };
}

function demoReport(): Report {
  const report = recording.report;
  const agentsSoFar = new Set(stepsDone().map((s) => s.agent));
  return {
    ...report,
    run: demoRun(),
    steps: stepsDone(),
    final_review: reached("review") ? report.final_review : null,
    final_tests: reached("run_tests") ? report.final_tests : null,
    files: reached("develop") ? report.files : [],
    usage_by_agent: demoReplay.finished
      ? report.usage_by_agent
      : report.usage_by_agent.filter((u) =>
          [...agentsSoFar].some((node) => AGENT_OF_NODE[node] === u.agent),
        ),
  };
}

const AGENT_OF_NODE: Record<string, string> = {
  plan: "planner",
  develop: "developer",
  revise: "developer",
  review: "reviewer",
  write_tests: "tester",
  triage: "tester",
};

const later = <T>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), 60));

/** Error with the same shape the API client throws. */
export class DemoError extends Error {}

/** Answer API calls for the demo run and project from the recording; pass the rest on. */
export function withDemo<
  A extends {
    getRun(id: string): Promise<Run>;
    report(id: string): Promise<Report>;
    getProject(id: string): Promise<ProjectDetail>;
    files(id: string): Promise<FileEntry[]>;
    fileContent(id: string, path: string): Promise<{ path: string; content: string }>;
    reviews(id: string): Promise<Review[]>;
    tests(id: string): Promise<TestRun[]>;
    git(id: string): Promise<GitInfo>;
    decide(approvalId: string, decision: Decision): Promise<Approval>;
    cancelRun(id: string): Promise<{ run_id: string; status: string }>;
    startRun(projectId: string): Promise<{ run_id: string; status: string }>;
    preview(id: string): Promise<Preview>;
  },
>(api: A): A {
  const demoApprovalIds = new Set(recording.approvals.map((a) => a.id));
  return {
    ...api,
    getRun: (id: string) => (isDemo(id) ? later(demoRun()) : api.getRun(id)),
    report: (id: string) => (isDemo(id) ? later(demoReport()) : api.report(id)),
    getProject: (id: string) =>
      isDemo(id)
        ? later({ ...recording.project, id: DEMO_PROJECT_ID, runs: [] })
        : api.getProject(id),
    files: (id: string) =>
      isDemo(id) ? later(reached("develop") ? recording.files : []) : api.files(id),
    fileContent: (id: string, path: string) =>
      isDemo(id)
        ? later({ path, content: recording.contents[path] ?? "" })
        : api.fileContent(id, path),
    reviews: (id: string) =>
      isDemo(id) ? later(reached("review") ? recording.reviews : []) : api.reviews(id),
    tests: (id: string) =>
      isDemo(id) ? later(reached("run_tests") ? recording.tests : []) : api.tests(id),
    git: (id: string) =>
      isDemo(id)
        ? later(
            demoReplay.finished
              ? recording.git
              : { initialized: false, branch: null, clean: null, files: [], commits: [] },
          )
        : api.git(id),
    decide: async (approvalId: string, decision: Decision) => {
      if (!demoApprovalIds.has(approvalId)) return api.decide(approvalId, decision);
      if (decision.decision !== "approve") {
        throw new DemoError(
          "The demo replays a recorded run in which both steps were approved. Approve to continue.",
        );
      }
      const approval = demoRun().pending_approval;
      demoReplay.approve();
      return later({ ...(approval as Approval), status: "approved" as const });
    },
    cancelRun: (id: string) => {
      if (!isDemo(id)) return api.cancelRun(id);
      demoReplay.restart();
      return later({ run_id: DEMO_RUN_ID, status: "RUNNING" });
    },
    startRun: (projectId: string) => {
      if (!isDemo(projectId)) return api.startRun(projectId);
      demoReplay.restart();
      return later({ run_id: DEMO_RUN_ID, status: "RUNNING" });
    },
    preview: (id: string) =>
      isDemo(id) ? later({ status: "stopped" as const, url: null, expires_at: null }) : api.preview(id),
  };
}
