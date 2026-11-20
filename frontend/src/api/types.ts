// Shapes returned by the backend (backend/app/api/schemas.py).

export type RunStatus =
  | "RUNNING"
  | "PAUSED"
  | "SUCCESS"
  | "NOT_COMMITTED"
  | "FAILED_REVIEW"
  | "FAILED_TESTS"
  | "NOT_EXECUTED"
  | "ERROR"
  | "CANCELLED";

export const ACTIVE_STATUSES: RunStatus[] = ["RUNNING", "PAUSED"];

export type ApprovalKind = "clarify" | "execute" | "commit";

export interface Project {
  id: string;
  name: string;
  requirement: string;
  created_at: string;
}

export interface RunSummary {
  id: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
}

export interface ProjectDetail extends Project {
  runs: RunSummary[];
}

export interface ClarifyPayload {
  kind: "clarify";
  questions: string[];
}
export interface ExecutePayload {
  kind: "execute";
  executor: string;
  workspace: string;
}
export interface CommitPayload {
  kind: "commit";
  workspace: string;
  files: string[];
  message: string;
}
export type ApprovalPayload = ClarifyPayload | ExecutePayload | CommitPayload;

export interface Approval {
  id: string;
  run_id: string;
  kind: ApprovalKind;
  status: "pending" | "approved" | "rejected" | "cancelled";
  payload: ApprovalPayload;
  answer: Record<string, unknown> | null;
  created_at: string;
  decided_at: string | null;
}

export interface Run {
  id: string;
  project_id: string;
  status: RunStatus;
  current_step: string | null;
  review_status: string | null;
  test_status: string | null;
  review_rounds: number;
  fix_rounds: number;
  workspace: string | null;
  model: string | null;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  commit_sha: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  pending_approval: Approval | null;
}

export interface FileEntry {
  path: string;
  size_bytes: number;
}

export interface Finding {
  file: string;
  line: number;
  severity: "high" | "medium" | "low";
  category: string;
  source: string;
  rule: string;
  message: string;
  suggested_fix: string;
}

export interface Review {
  round: number;
  verdict: "pass" | "changes_needed";
  summary: string;
  findings: Finding[];
}

export interface TestCase {
  name: string;
  outcome: "passed" | "failed" | "error" | "skipped";
  message: string;
}

export interface TriageItem {
  test: string;
  cause: "bad_code" | "bad_test" | "environment";
  file: string;
  reason: string;
  suggested_fix: string;
}

export interface TestRun {
  round: number;
  executor: string;
  status: "PASSED" | "FAILED" | "ERROR" | "NOT_EXECUTED";
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_ms: number;
  detail: string;
  triage: { items: TriageItem[]; summary: string } | null;
  cases: TestCase[];
}

export interface Step {
  agent: string;
  round: number;
  status: string;
  summary: string;
  finished_at: string | null;
}

export interface AgentUsage {
  agent: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Report {
  run: Run;
  steps: Step[];
  final_review: Review | null;
  final_tests: TestRun | null;
  files: FileEntry[];
  usage_by_agent: AgentUsage[];
}

export interface GitInfo {
  initialized: boolean;
  branch: string | null;
  clean: boolean | null;
  files: { status: string; path: string }[];
  commits: { commit: string; author: string; date: string; subject: string }[];
}

export interface Health {
  status: "ok";
  executor: string;
  model: string | null;
  llm_configured: boolean;
  llm_error: string | null;
  git_available: boolean;
}

export type Decision =
  | { decision: "approve"; answers?: string[]; message?: string }
  | { decision: "reject" }
  | { decision: "cancel" };
