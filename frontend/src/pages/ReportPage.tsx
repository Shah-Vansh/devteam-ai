import type { CSSProperties } from "react";
import { Loading, StatusBadge } from "../components/common";
import { formatTokens, NODE_AGENT } from "../lib/agents";
import { stageOfNode } from "../lib/pipeline";
import { useRunContext } from "./RunLayout";

const VERDICT: Record<string, string> = {
  SUCCESS: "Reviewed, tested in the sandbox and committed.",
  NOT_COMMITTED: "Reviewed and tested, but not committed.",
  FAILED_REVIEW: "Stopped: the review still found high-severity problems.",
  FAILED_TESTS: "Stopped: tests were still failing after the fix rounds.",
  NOT_EXECUTED: "Reviewed, but the tests were never executed.",
  ERROR: "Stopped by an error.",
  CANCELLED: "Cancelled.",
  RUNNING: "Still running.",
  PAUSED: "Waiting for your decision.",
};

const TONE: Record<string, string> = {
  SUCCESS: "success",
  FAILED_REVIEW: "failure",
  FAILED_TESTS: "failure",
  ERROR: "failure",
};

function Ring({ pct, label, color }: { pct: number; label: string; color: string }) {
  const style = { "--pct": pct, "--ring-color": color } as CSSProperties;
  return <span className="ring" style={style} data-label={label} aria-hidden="true" />;
}

function nodeTone(node: string): string {
  const agent = NODE_AGENT[node];
  if (agent) return agent;
  const stage = stageOfNode(node);
  return stage === "approve_run" || stage === "approve_commit" ? "gate" : "system";
}

export function ReportPage() {
  const { run, report } = useRunContext();
  if (!report) return <Loading what="Loading report" />;
  const tests = report.final_tests;
  const review = report.final_review;
  const failing = tests?.cases.filter((c) => c.outcome === "failed" || c.outcome === "error") ?? [];
  const testTotal = tests ? tests.passed + tests.failed + tests.errors : 0;
  const testPct = testTotal ? Math.round((tests!.passed / testTotal) * 100) : 0;
  const counts = { high: 0, medium: 0, low: 0 };
  for (const f of review?.findings ?? []) counts[f.severity] += 1;
  const maxTokens = Math.max(1, ...report.usage_by_agent.map((u) => u.input_tokens + u.output_tokens));

  return (
    <div className="report">
      <section className="panel span-12 verdict" aria-label="Verdict">
        <div className={`verdict-main ${TONE[run.status] ?? "neutral"}`}>
          <div className="eyebrow">Verdict</div>
          <h2>
            <StatusBadge status={run.status} />
          </h2>
          <p className="big">{VERDICT[run.status] ?? run.status}</p>
          {run.error && run.status !== "SUCCESS" && <p className="muted">{run.error}</p>}
          {run.commit_sha && (
            <p className="muted" style={{ marginTop: 8 }}>
              commit <code>{run.commit_sha.slice(0, 7)}</code> · {run.review_rounds} review rounds ·{" "}
              {run.fix_rounds} fix rounds
            </p>
          )}
        </div>
        {/* Review and tests are separate signals: a passed review never means passed tests. */}
        <div className="gauge">
          <Ring
            pct={review ? (review.verdict === "pass" ? 100 : 35) : 0}
            label={review ? (review.verdict === "pass" ? "✓" : "!") : "—"}
            color={review?.verdict === "pass" ? "var(--good)" : "var(--bad)"}
          />
          <div>
            <h3>Review</h3>
            <div className="big">
              <StatusBadge status={run.review_status} />
            </div>
            <p className="muted mono small">
              {counts.high} high · {counts.medium} med · {counts.low} low
            </p>
          </div>
        </div>
        <div className="gauge">
          <Ring
            pct={testPct}
            label={tests ? `${testPct}%` : "—"}
            color={tests?.status === "PASSED" ? "var(--good)" : "var(--bad)"}
          />
          <div>
            <h3>Tests</h3>
            <div className="big">
              <StatusBadge status={run.test_status} />
            </div>
            <p className="muted mono small">
              {tests ? `${tests.passed}/${testTotal} passed · ${tests.executor}` : "not run"}
            </p>
          </div>
        </div>
      </section>

      <section className="panel span-8">
        <div className="panel-head">
          <h2>Tests</h2>
          <span className="spacer" />
          {tests && (
            <span className="muted mono small">
              {(tests.duration_ms / 1000).toFixed(1)} s in {tests.executor}
            </span>
          )}
        </div>
        {!tests ? (
          <p className="empty">No test run.</p>
        ) : (
          <>
            <p>
              <StatusBadge status={tests.status} /> {tests.passed} passed, {tests.failed} failed,{" "}
              {tests.errors} errors
            </p>
            <div className="test-grid" aria-hidden="true">
              {tests.cases.map((c) => (
                <span key={c.name} className={`test-cell ${c.outcome}`} title={c.name} />
              ))}
            </div>
            {tests.detail && <p className="muted">{tests.detail}</p>}
            <table className="data">
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {tests.cases.map((c) => (
                  <tr key={c.name}>
                    <td>
                      <code>{c.name}</code>
                    </td>
                    <td>
                      <span
                        className={`badge ${c.outcome === "passed" ? "good" : c.outcome === "skipped" ? "neutral" : "bad"}`}
                      >
                        {c.outcome}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {failing.length > 0 && (
              <details>
                <summary>Failure messages ({failing.length})</summary>
                {failing.map((c) => (
                  <pre key={c.name} className="code small">
                    {c.name}
                    {"\n"}
                    {c.message}
                  </pre>
                ))}
              </details>
            )}
            {tests.triage && (
              <>
                <h3 style={{ margin: "16px 0 6px" }}>Triage</h3>
                <p className="muted">{tests.triage.summary}</p>
                {tests.triage.items.map((item) => (
                  <div key={item.test} className="triage-item">
                    <span className={`badge ${item.cause === "bad_code" ? "bad" : item.cause === "bad_test" ? "warn" : "neutral"}`}>
                      {item.cause.replace("_", " ")}
                    </span>
                    <span>
                      <code>{item.test}</code> — {item.reason}
                    </span>
                  </div>
                ))}
              </>
            )}
          </>
        )}
      </section>

      <section className="panel span-4">
        <div className="panel-head">
          <h2>LLM usage</h2>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Calls</th>
              <th>Tokens</th>
            </tr>
          </thead>
          <tbody>
            {report.usage_by_agent.map((u) => (
              <tr key={u.agent}>
                <td>{u.agent}</td>
                <td className="mono">{u.calls}</td>
                <td>
                  <div className="bar" title={`${u.input_tokens} in · ${u.output_tokens} out`}>
                    <i className="in" style={{ width: `${(u.input_tokens / maxTokens) * 100}%` }} />
                    <i className="out" style={{ width: `${(u.output_tokens / maxTokens) * 100}%` }} />
                  </div>
                  <span className="mono dim small">
                    {formatTokens(u.input_tokens)} / {formatTokens(u.output_tokens)}
                  </span>
                </td>
              </tr>
            ))}
            <tr className="total">
              <td>Total</td>
              <td className="mono">{run.llm_calls}</td>
              <td className="mono">
                {formatTokens(run.input_tokens)} / {formatTokens(run.output_tokens)}
              </td>
            </tr>
          </tbody>
        </table>
        <div className="legend">
          <span>
            <i style={{ background: "var(--accent)" }} />
            input
          </span>
          <span>
            <i style={{ background: "var(--cyan)" }} />
            output
          </span>
        </div>
      </section>

      <section className="panel span-6">
        <div className="panel-head">
          <h2>Final review</h2>
        </div>
        {!review ? (
          <p className="empty">No review yet.</p>
        ) : (
          <>
            <p style={{ marginBottom: 10 }}>
              <StatusBadge status={review.verdict} /> <span className="muted">round {review.round}</span>
            </p>
            <p className="muted">{review.summary}</p>
            <p className="mono dim small" style={{ marginTop: 10 }}>
              {counts.high} high · {counts.medium} medium · {counts.low} low
            </p>
          </>
        )}
      </section>

      <section className="panel span-6">
        <div className="panel-head">
          <h2>Steps</h2>
          <span className="spacer" />
          <span className="dim mono small">
            {report.steps.length} steps
          </span>
        </div>
        {report.steps.length === 0 ? (
          <p className="empty">No steps recorded yet.</p>
        ) : (
          <ol className="timeline">
            {report.steps.map((s, i) => (
              <li key={i}>
                <span className={`node ${nodeTone(s.agent)}`} aria-hidden="true" />
                <code>{s.agent}</code>
                <span className="muted">{s.summary}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
