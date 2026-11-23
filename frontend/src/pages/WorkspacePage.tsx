import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Finding, GitInfo } from "../api/types";
import { ErrorBox, Loading } from "../components/common";
import { Icon } from "../components/icons";
import { type AsyncState, useAsync } from "../hooks/useAsync";
import { buildTree, highlightLines, type TreeNode } from "../lib/highlight";
import { useRunContext } from "./RunLayout";

const GIT_STATUS: Record<string, string> = { "??": "U", M: "M", A: "A", D: "D" };
const SEVERITY_ICON = { high: "alert", medium: "alert", low: "info" } as const;

export function WorkspacePage() {
  const { run } = useRunContext();
  // Reload the lists whenever the run moves on (status or step changes).
  const key = `${run.status}-${run.current_step}-${run.commit_sha}`;
  const files = useAsync(() => api.files(run.id), [run.id, key]);
  const reviews = useAsync(() => api.reviews(run.id), [run.id, key]);
  const git = useAsync(() => api.git(run.id), [run.id, key]);
  const [selected, setSelected] = useState<string>();
  const [focusLine, setFocusLine] = useState<number>();

  useEffect(() => {
    if (!selected && files.data?.length) {
      setSelected(files.data.find((f) => f.path === "app/main.py")?.path ?? files.data[0]?.path);
    }
  }, [files.data, selected]);

  const findings = reviews.data?.at(-1)?.findings ?? [];
  const byFile = new Map<string, Finding[]>();
  for (const finding of findings) {
    byFile.set(finding.file, [...(byFile.get(finding.file) ?? []), finding]);
  }

  if (files.error) return <ErrorBox error={files.error} />;
  if (!files.data) return <Loading what="Loading files" />;
  if (files.data.length === 0) return <p className="panel empty">No files written yet.</p>;

  function open(path: string, line?: number) {
    setSelected(path);
    setFocusLine(line);
  }

  return (
    <div className="ide">
      <nav className="explorer" aria-label="Files">
        <div className="side-title">
          <span>Explorer</span>
          <span>{files.data.length} files</span>
        </div>
        <Tree nodes={buildTree(files.data.map((f) => f.path))} selected={selected} byFile={byFile} onOpen={open} />
        <GitPanel git={git} />
      </nav>
      <div className="editor">
        {selected ? (
          <Editor
            runId={run.id}
            path={selected}
            version={key}
            findings={byFile.get(selected) ?? []}
            focusLine={focusLine}
          />
        ) : (
          <p className="empty">Select a file.</p>
        )}
        <Problems findings={findings} round={reviews.data?.at(-1)?.round} onOpen={open} />
      </div>
    </div>
  );
}

function Tree(props: {
  nodes: TreeNode[];
  selected?: string;
  byFile: Map<string, Finding[]>;
  onOpen: (path: string) => void;
}) {
  const { nodes, selected, byFile, onOpen } = props;
  return (
    <ul className="tree">
      {nodes.map((node) =>
        node.isFile ? (
          <li key={node.path}>
            <button
              type="button"
              className={`tree-row ${node.path === selected ? "selected" : ""}`}
              aria-current={node.path === selected ? "true" : undefined}
              onClick={() => onOpen(node.path)}
              title={node.path}
            >
              <Icon name="file" />
              <span className="name">{node.name}</span>
              <FindingCount findings={byFile.get(node.path)} />
            </button>
          </li>
        ) : (
          <li key={node.path}>
            <div className="tree-row folder">
              <Icon name="folder" />
              <span className="name">{node.name}</span>
            </div>
            <Tree nodes={node.children} selected={selected} byFile={byFile} onOpen={onOpen} />
          </li>
        ),
      )}
    </ul>
  );
}

function FindingCount({ findings }: { findings?: Finding[] }) {
  if (!findings?.length) return null;
  const high = findings.some((f) => f.severity === "high");
  return (
    <span className={`count ${high ? "high" : ""}`} aria-label={`${findings.length} findings`}>
      {findings.length}
    </span>
  );
}

function Editor(props: {
  runId: string;
  path: string;
  version: string;
  findings: Finding[];
  focusLine?: number;
}) {
  const { runId, path, version, findings, focusLine } = props;
  const content = useAsync(() => api.fileContent(runId, path), [runId, path, version]);
  const focusRef = useRef<HTMLDivElement>(null);
  const severityOf = new Map(findings.map((f) => [f.line, f.severity]));

  useEffect(() => {
    focusRef.current?.scrollIntoView?.({ block: "center" });
  }, [focusLine, content.data]);

  return (
    <>
      <div className="editor-tabs" role="tablist" aria-label="Open files">
        <span className="editor-tab active" role="tab" aria-selected="true">
          <Icon name="file" />
          {path.split("/").at(-1)}
        </span>
      </div>
      <div className="breadcrumbs" aria-label={`File ${path}`}>
        {path.split("/").map((part, i, all) => (
          <span key={i}>
            {i === all.length - 1 ? <b>{part}</b> : part}
            {i < all.length - 1 && " › "}
          </span>
        ))}
      </div>
      {content.error && <ErrorBox error={content.error} />}
      {!content.error && content.data?.path !== path && <p className="muted code-loading">Opening {path}…</p>}
      {content.data && content.data.path === path && (
        <pre className="code" aria-label={`Contents of ${path}`}>
          {highlightLines(path, content.data.content).map((tokens, i) => {
            const n = i + 1;
            const severity = severityOf.get(n);
            const classes = ["line"];
            if (severity) classes.push("flagged", severity);
            if (n === focusLine) classes.push("focus");
            return (
              <div key={i} className={classes.join(" ")} ref={n === focusLine ? focusRef : undefined}>
                <span className="ln">{n}</span>
                <span>
                  {tokens.length === 0
                    ? " "
                    : tokens.map((t, j) =>
                        t.kind === "plain" ? (
                          t.text
                        ) : (
                          <span key={j} className={`tok-${t.kind}`}>
                            {t.text}
                          </span>
                        ),
                      )}
                </span>
              </div>
            );
          })}
        </pre>
      )}
    </>
  );
}

function Problems(props: {
  findings: Finding[];
  round?: number;
  onOpen: (path: string, line?: number) => void;
}) {
  const { findings, round, onOpen } = props;
  return (
    <section className="problems" aria-label="Review findings">
      <div className="problems-head">
        <span>Problems</span>
        <span className="badge plain">{findings.length}</span>
        {round !== undefined && <span className="dim">latest review · round {round}</span>}
      </div>
      {findings.length === 0 ? (
        <p className="empty">No findings in the latest review.</p>
      ) : (
        <ul>
          {findings.map((f, i) => (
            <li key={i}>
              <button type="button" className={`problem ${f.severity}`} onClick={() => onOpen(f.file, f.line || undefined)}>
                <Icon name={SEVERITY_ICON[f.severity]} />
                <span>
                  <span className="problem-msg">{f.message}</span>
                  {f.suggested_fix && <span className="problem-fix"> — {f.suggested_fix}</span>}
                </span>
                <span className="problem-where">
                  {f.source}
                  {f.rule ? ` ${f.rule}` : ""} · {f.file}
                  {f.line ? `:${f.line}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function GitPanel({ git }: { git: AsyncState<GitInfo> }) {
  return (
    <div className="scm">
      <div className="side-title">
        <span>Source control</span>
      </div>
      <div className="scm-body">
        {git.error && <p className="error">Git: {git.error.message}</p>}
        {git.data && !git.data.initialized && (
          <p className="dim">No repository yet: one is created when you approve the commit.</p>
        )}
        {git.data?.initialized && (
          <>
            <div className="scm-branch">
              <Icon name="branch" width={14} height={14} />
              <span>{git.data.branch}</span>
              <span className={`badge ${git.data.clean ? "good" : "warn"}`}>
                {git.data.clean ? "clean" : "uncommitted changes"}
              </span>
            </div>
            {git.data.files.length > 0 && (
              <ul className="commits">
                {git.data.files.map((f) => (
                  <li key={f.path}>
                    <span className="mono warn">{GIT_STATUS[f.status] ?? f.status}</span>
                    <code>{f.path}</code>
                  </li>
                ))}
              </ul>
            )}
            <ol className="commits" aria-label="Commits">
              {git.data.commits.map((c) => (
                <li key={c.commit}>
                  <span className="commit-dot" aria-hidden="true" />
                  <span>
                    <span className="commit-subject">{c.subject}</span>
                    <span className="commit-meta">
                      {" "}
                      {c.commit.slice(0, 7)} · {c.author}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
