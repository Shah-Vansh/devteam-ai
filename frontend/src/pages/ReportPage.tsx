import { ErrorBox, Loading, Stat, StatusBadge } from "../components/common";
import { formatTokens } from "../lib/agents";
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

export function ReportPage() {
  const { run, report } = useRunContext();
  if (!report) return <Loading what="Loading report" />;
  const tests = report.final_tests;
  const review = report.final_review;
  const failing = tests?.cases.filter((c) => c.outcome === "failed" || c.outcome === "error") ?? [];

  return (
    <div className="report">
      <section className="panel verdict">
        <h2>Verdict</h2>
        <p className="big">
          <StatusBadge status={run.status} /> {VERDICT[run.status] ?? run.status}
        </p>
        {run.error && run.status !== "SUCCESS" && <p className="muted">{run.error}</p>}
        {/* Review and tests are separate signals: a passed review never means passed tests. */}
        <div className="stats">
          <Stat label="review" value={<StatusBadge status={run.review_status} />} />
          <Stat label="tests" value={<StatusBadge status={run.test_status} />} />
          <Stat label="review rounds" value={run.review_rounds} />
          <Stat label="fix rounds" value={run.fix_rounds} />
          <Stat label="commit" value={run.commit_sha ? <code>{run.commit_sha.slice(0, 7)}</code> : "—"} />
        </div>
      </section>

      <section className="panel">
        <h2>Tests</h2>
        {!tests ? (
          <p className="muted">No test run.</p>
        ) : (
          <>
            <p>
              <StatusBadge status={tests.status} /> {tests.passed} passed, {tests.failed} failed,{" "}
              {tests.errors} errors in {(tests.duration_ms / 1000).toFixed(1)} s ({tests.executor})
            </p>
            {tests.detail && <p className="muted">{tests.detail}</p>}
            <table>
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
                      <span className={`badge ${c.outcome === "passed" ? "good" : c.outcome === "skipped" ? "neutral" : "bad"}`}>
                        {c.outcome}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {failing.length > 0 && (
              <details>
                <summary>Failure messages</summary>
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
                <h3>Triage</h3>
                <p className="muted">{tests.triage.summary}</p>
                <ul>
                  {tests.triage.items.map((item) => (
                    <li key={item.test}>
                      <span className="badge neutral">{item.cause.replace("_", " ")}</span>{" "}
                      <code>{item.test}</code>: {item.reason}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <h2>Final review</h2>
        {!review ? (
          <p className="muted">No review yet.</p>
        ) : (
          <>
            <p>
              <StatusBadge status={review.verdict} /> round {review.round}: {review.summary}
            </p>
            <p className="muted">
              {["high", "medium", "low"]
                .map((s) => `${review.findings.filter((f) => f.severity === s).length} ${s}`)
                .join(" · ")}
            </p>
          </>
        )}
      </section>

      <section className="panel">
        <h2>LLM usage</h2>
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Calls</th>
              <th>Tokens in</th>
              <th>Tokens out</th>
            </tr>
          </thead>
          <tbody>
            {report.usage_by_agent.map((u) => (
              <tr key={u.agent}>
                <td>{u.agent}</td>
                <td>{u.calls}</td>
                <td>{formatTokens(u.input_tokens)}</td>
                <td>{formatTokens(u.output_tokens)}</td>
              </tr>
            ))}
            <tr className="total">
              <td>Total</td>
              <td>{run.llm_calls}</td>
              <td>{formatTokens(run.input_tokens)}</td>
              <td>{formatTokens(run.output_tokens)}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>Steps</h2>
        {report.steps.length === 0 ? (
          <ErrorBox error={new Error("no steps recorded yet")} />
        ) : (
          <ol className="steps">
            {report.steps.map((s, i) => (
              <li key={i}>
                <code>{s.agent}</code> <span className="muted">{s.summary}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
