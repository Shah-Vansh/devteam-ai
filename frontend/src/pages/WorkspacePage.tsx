import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Finding } from "../api/types";
import { ErrorBox, Loading } from "../components/common";
import { useAsync } from "../hooks/useAsync";
import { useRunContext } from "./RunLayout";

const GIT_STATUS: Record<string, string> = { "??": "new", M: "modified", A: "added", D: "deleted" };

export function WorkspacePage() {
  const { run } = useRunContext();
  // Reload the lists whenever the run moves on (status or step changes).
  const key = `${run.status}-${run.current_step}-${run.commit_sha}`;
  const files = useAsync(() => api.files(run.id), [run.id, key]);
  const reviews = useAsync(() => api.reviews(run.id), [run.id, key]);
  const git = useAsync(() => api.git(run.id), [run.id, key]);
  const [selected, setSelected] = useState<string>();

  useEffect(() => {
    if (!selected && files.data?.length) {
      setSelected(files.data.find((f) => f.path === "app/main.py")?.path ?? files.data[0]?.path);
    }
  }, [files.data, selected]);

  const latestReview = reviews.data?.at(-1);
  const findingsByFile = new Map<string, Finding[]>();
  for (const finding of latestReview?.findings ?? []) {
    findingsByFile.set(finding.file, [...(findingsByFile.get(finding.file) ?? []), finding]);
  }

  if (files.error) return <ErrorBox error={files.error} />;
  if (!files.data) return <Loading what="Loading files" />;
  if (files.data.length === 0) return <p className="panel muted">No files written yet.</p>;

  return (
    <div className="workspace">
      <nav className="panel tree" aria-label="Files">
        <h2>Files</h2>
        <ul>
          {files.data.map((file) => {
            const count = findingsByFile.get(file.path)?.length ?? 0;
            return (
              <li key={file.path}>
                <button
                  type="button"
                  className={file.path === selected ? "file selected" : "file"}
                  aria-current={file.path === selected ? "true" : undefined}
                  onClick={() => setSelected(file.path)}
                >
                  <code>{file.path}</code>
                  {count > 0 && <span className="count">{count}</span>}
                </button>
              </li>
            );
          })}
        </ul>
        <GitPanel git={git} />
      </nav>
      {selected && (
        <FileView
          runId={run.id}
          path={selected}
          version={key}
          findings={findingsByFile.get(selected) ?? []}
        />
      )}
    </div>
  );
}

function FileView(props: { runId: string; path: string; version: string; findings: Finding[] }) {
  const { runId, path, version, findings } = props;
  const content = useAsync(() => api.fileContent(runId, path), [runId, path, version]);
  const flagged = new Set(findings.map((f) => f.line));

  return (
    <section className="panel viewer" aria-label={`File ${path}`}>
      <h2>
        <code>{path}</code>
      </h2>
      {content.error && <ErrorBox error={content.error} />}
      {content.data && (
        <pre className="code">
          {content.data.content.split("\n").map((line, i) => (
            <div key={i} className={flagged.has(i + 1) ? "line flagged" : "line"}>
              <span className="ln">{i + 1}</span>
              <span>{line || " "}</span>
            </div>
          ))}
        </pre>
      )}
      <h3>Review findings in this file</h3>
      {findings.length === 0 ? (
        <p className="muted">None in the latest review.</p>
      ) : (
        <ul className="findings">
          {findings.map((f, i) => (
            <li key={i} className={`finding ${f.severity}`}>
              <span className={`badge ${f.severity === "high" ? "bad" : "warn"}`}>
                {f.severity}
              </span>{" "}
              <span className="muted">
                {f.source}
                {f.rule ? ` ${f.rule}` : ""}
                {f.line ? ` · line ${f.line}` : ""}
              </span>
              <div>{f.message}</div>
              {f.suggested_fix && <div className="muted">Fix: {f.suggested_fix}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function GitPanel({ git }: { git: ReturnType<typeof useAsync<Awaited<ReturnType<typeof api.git>>>> }) {
  if (git.error) return <p className="error">Git: {git.error.message}</p>;
  if (!git.data) return null;
  if (!git.data.initialized) {
    return (
      <div className="git">
        <h3>Git</h3>
        <p className="muted">No repository yet: one is created when you approve the commit.</p>
      </div>
    );
  }
  return (
    <div className="git">
      <h3>
        Git <code>{git.data.branch}</code>{" "}
        <span className={`badge ${git.data.clean ? "good" : "warn"}`}>
          {git.data.clean ? "clean" : "uncommitted changes"}
        </span>
      </h3>
      {git.data.files.length > 0 && (
        <ul>
          {git.data.files.map((f) => (
            <li key={f.path}>
              <span className="muted">{GIT_STATUS[f.status] ?? f.status}</span> <code>{f.path}</code>
            </li>
          ))}
        </ul>
      )}
      <ol className="commits">
        {git.data.commits.map((c) => (
          <li key={c.commit}>
            <code>{c.commit.slice(0, 7)}</code> {c.subject} <span className="muted">· {c.author}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
