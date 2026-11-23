import { useState } from "react";
import type { Approval, Decision } from "../api/types";
import { Icon } from "./icons";

interface Props {
  approval: Approval;
  onDecide: (decision: Decision) => Promise<void>;
}

/** A human gate in the pipeline: answer the Planner's questions, allow test execution in
 * the sandbox, or approve the commit. Every gate can also cancel the whole run. */
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
    <button
      type="button"
      className="danger"
      disabled={busy}
      onClick={() => decide({ decision: "cancel" })}
    >
      <Icon name="x" width={14} height={14} />
      Cancel run
    </button>
  );

  return (
    <section className="gate-card" aria-labelledby="approval-title">
      {payload.kind === "clarify" && (
        <>
          <div className="gate-head">
            <span className="gate-icon">
              <Icon name="plan" />
            </span>
            <div>
              <div className="eyebrow">gate · clarify</div>
              <h2 id="approval-title">The Planner has questions</h2>
            </div>
          </div>
          <p>Answer what matters. Empty answers keep the Planner's own assumptions.</p>
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
          <div className="gate-head">
            <span className="gate-icon">
              <Icon name="shield" />
            </span>
            <div>
              <div className="eyebrow">gate · execute</div>
              <h2 id="approval-title">Run the generated tests?</h2>
            </div>
          </div>
          <p>
            The code and tests will be sent to the <strong>{payload.executor}</strong> sandbox:
            a fresh microVM, packages from a pinned allow-list, internet switched off before the
            tests start.
          </p>
          <ul className="gate-facts" aria-label="Sandbox guarantees">
            <li>fresh microVM</li>
            <li>pinned packages</li>
            <li>internet off</li>
            <li>no secrets inside</li>
          </ul>
          <div className="actions">
            <button
              type="button"
              className="good"
              disabled={busy}
              onClick={() => decide({ decision: "approve" })}
            >
              <Icon name="play" width={14} height={14} />
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
          <div className="gate-head">
            <span className="gate-icon">
              <Icon name="commit" />
            </span>
            <div>
              <div className="eyebrow">gate · commit</div>
              <h2 id="approval-title">Tests passed. Commit these files?</h2>
            </div>
          </div>
          <p>
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
              className="good"
              disabled={busy || !message.trim()}
              onClick={() => decide({ decision: "approve", message })}
            >
              <Icon name="commit" width={14} height={14} />
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
        <p role="alert" className="error" style={{ marginTop: 12 }}>
          {error}
        </p>
      )}
    </section>
  );
}
