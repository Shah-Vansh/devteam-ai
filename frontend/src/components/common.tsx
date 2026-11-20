import type { ReactNode } from "react";
import type { RunStatus } from "../api/types";

const STATUS_TONE: Record<string, string> = {
  RUNNING: "info",
  PAUSED: "warn",
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

export function StatusBadge({ status }: { status: RunStatus | string | null | undefined }) {
  if (!status) return <span className="badge neutral">—</span>;
  const label = status.replaceAll("_", " ").toLowerCase();
  return <span className={`badge ${STATUS_TONE[status] ?? "neutral"}`}>{label}</span>;
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p className="muted" role="status">
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
