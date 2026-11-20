import { useState } from "react";
import type { Approval, Decision } from "../api/types";

interface Props {
  approval: Approval;
  onDecide: (decision: Decision) => Promise<void>;
}

/** The human pause of a run: answer the Planner's questions, allow test execution in the
 * sandbox, or approve the commit. Every form can also cancel the whole run. */
export function ApprovalPanel({ approval, onDecide }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const payload = approval.payload;
  const [answers, setAnswers] = useState<string[]>(
    payload.kind === "clarify" ? payload.questions.map(() => "") : [],
  );
  const [message, setMessage] = useState(payload.kind === "commit" ? payload.message : "");

  async function decide(decision: Decision) {
    setBusy(true);
    setError(undefined);
    try {
      await onDecide(decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const cancel = (
    <button type="button" className="danger" disabled={busy} onClick={() => decide({ decision: "cancel" })}>
      Cancel run
    </button>
  );

  return (
    <section className="panel approval" aria-labelledby="approval-title">
      {payload.kind === "clarify" && (
        <>
          <h2 id="approval-title">The Planner has questions</h2>
          <p className="muted">
            Answer what matters. Empty answers keep the Planner's own assumptions.
          </p>
          {payload.questions.map((question, i) => (
            <label key={question} className="field">
              <span>{question}</span>
              <textarea
                rows={2}
                value={answers[i] ?? ""}
                onChange={(e) =>
                  setAnswers((all) => all.map((a, j) => (j === i ? e.target.value : a)))
                }
              />
            </label>
          ))}
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => decide({ decision: "approve", answers })}
            >
              Send answers
            </button>
            <button type="button" disabled={busy} onClick={() => decide({ decision: "reject" })}>
              Keep assumptions
            </button>
            {cancel}
          </div>
        </>
      )}

      {payload.kind === "execute" && (
        <>
          <h2 id="approval-title">Run the generated tests?</h2>
          <p>
            The code and tests will be sent to the <strong>{payload.executor}</strong> sandbox:
            a fresh microVM, packages from a pinned allow-list, internet switched off before the
            tests start.
          </p>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => decide({ decision: "approve" })}
            >
              Run tests
            </button>
            <button type="button" disabled={busy} onClick={() => decide({ decision: "reject" })}>
              Do not run
            </button>
            {cancel}
          </div>
        </>
      )}

      {payload.kind === "commit" && (
        <>
          <h2 id="approval-title">Tests passed. Commit these files?</h2>
          <p className="muted">
            {payload.files.length} files in <code>{payload.workspace}</code>. The commit is only
            accepted for exactly these files: anything changed after this approval is refused.
          </p>
          <ul className="file-list">
            {payload.files.map((file) => (
              <li key={file}>
                <code>{file}</code>
              </li>
            ))}
          </ul>
          <label className="field">
            <span>Commit message</span>
            <textarea rows={5} value={message} onChange={(e) => setMessage(e.target.value)} />
          </label>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={busy || !message.trim()}
              onClick={() => decide({ decision: "approve", message })}
            >
              Commit
            </button>
            <button type="button" disabled={busy} onClick={() => decide({ decision: "reject" })}>
              Do not commit
            </button>
            {cancel}
          </div>
        </>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  );
}
