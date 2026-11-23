import type { ReactNode } from "react";
import type { RunStatus } from "../api/types";

const STATUS_TONE: Record<string, string> = {
  RUNNING: "info live",
  PAUSED: "warn live",
  SUCCESS: "good",
  NOT_COMMITTED: "neutral",
  NOT_EXECUTED: "neutral",
  CANCELLED: "neutral",
  FAILED_REVIEW: "bad",
  FAILED_TESTS: "bad",
  ERROR: "bad",
  pass: "good",
  changes_needed: "bad",
  PASSED: "good",
  FAILED: "bad",
};

const STATUS_LABEL: Record<string, string> = {
  PAUSED: "waiting for you",
  changes_needed: "changes needed",
};

export function StatusBadge({ status }: { status: RunStatus | string | null | undefined }) {
  if (!status) return <span className="badge plain">—</span>;
  const label = STATUS_LABEL[status] ?? status.replaceAll("_", " ").toLowerCase();
  return <span className={`badge ${STATUS_TONE[status] ?? "neutral"}`}>{label}</span>;
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p className="empty" role="status">
      {what}…
    </p>
  );
}

export function ErrorBox({ error, children }: { error: Error; children?: ReactNode }) {
  return (
    <div role="alert" className="panel error-box">
      <strong>Something went wrong.</strong> {error.message}
      {children}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
