import { type FormEvent, Fragment, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectDetail } from "../api/types";
import { ErrorBox, Loading, StatusBadge } from "../components/common";
import { Icon } from "../components/icons";
import { useAsync } from "../hooks/useAsync";

const MAX_REQUIREMENT = 4000;

const EXAMPLES = [
  { name: "notes-api", requirement: "Build a notes API with create, list, get by id and delete. Keep data in memory." },
  { name: "url-shortener", requirement: "Build a URL shortener API that creates short codes, redirects them, and counts clicks per link." },
  { name: "bookmarks", requirement: "Build a bookmarks API where each bookmark has a URL, title and tags, with filtering by tag." },
];

const FLOW = ["plan", "develop", "review", "tests", "⛩ approve", "sandbox", "fix loop", "⛩ approve", "commit"];

export function NewProjectForm({ onStarted }: { onStarted: (runId: string) => void }) {
  const [name, setName] = useState("");
  const [requirement, setRequirement] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const project = await api.createProject(name.trim(), requirement.trim());
      const run = await api.startRun(project.id);
      onStarted(run.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  const tooLong = requirement.length > MAX_REQUIREMENT;
  return (
    <form className="composer" onSubmit={submit} aria-labelledby="new-project">
      <div className="composer-bar">
        <Icon name="terminal" width={14} height={14} />
        <span id="new-project">New project</span>
        <span style={{ marginLeft: "auto" }}>python · fastapi</span>
      </div>
      <div className="composer-body">
        <label className="field">
          <span>Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            placeholder="notes-api"
            required
          />
        </label>
        <label className="field tight">
          <span>Requirement</span>
          <div className="prompt-box">
            <textarea
              rows={5}
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              placeholder="Build a todo API with create, list, mark as done and delete"
              aria-describedby="requirement-count"
              required
            />
          </div>
        </label>
        {/* Outside the label, so the field's accessible name stays "Requirement". */}
        <p id="requirement-count" className={`hint counter ${tooLong ? "error" : ""}`}>
          {requirement.length} / {MAX_REQUIREMENT}
        </p>
        <div className="examples" aria-label="Examples">
          {EXAMPLES.map((example) => (
            <button
              key={example.name}
              type="button"
              className="example"
              onClick={() => {
                setName(example.name);
                setRequirement(example.requirement);
              }}
            >
              {example.name}
            </button>
          ))}
        </div>
        <div className="composer-foot">
          <label className="field" style={{ margin: 0, flex: "1 1 200px" }}>
            <span>Project type</span>
            <select disabled value="fastapi">
              <option value="fastapi">Python FastAPI service</option>
            </select>
          </label>
          <button
            type="submit"
            className="primary"
            disabled={busy || !name.trim() || !requirement.trim() || tooLong}
            style={{ alignSelf: "flex-end" }}
          >
            <Icon name="play" width={14} height={14} />
            {busy ? "Starting…" : "Create and start"}
          </button>
        </div>
        {error && (
          <p role="alert" className="run-error">
            {error}
          </p>
        )}
      </div>
    </form>
  );
}

export function HomePage() {
  const navigate = useNavigate();
  const projects = useAsync(async () => {
    const list = await api.listProjects();
    // A local, single-user tool: one request per project is fine.
    return Promise.all(list.map((p) => api.getProject(p.id)));
  }, []);

  return (
    <>
      <div className="hero">
        <div className="hero-copy">
          <div className="eyebrow">Multi-agent software engineering</div>
          <h1>
            From one sentence to a <em>reviewed, tested and committed</em> API.
          </h1>
          <p>
            Four agents plan, write, review and test a FastAPI service. Generated code only runs in
            an isolated microVM, and nothing is executed or committed until you approve it.
          </p>
          <div className="flow-strip" aria-label="Pipeline stages">
            {FLOW.map((step, i) => (
              <Fragment key={i}>
                {i > 0 && <span className="dim">→</span>}
                <span className={`chip ${step.startsWith("⛩") ? "gate" : ""}`}>{step}</span>
              </Fragment>
            ))}
          </div>
        </div>
        <NewProjectForm onStarted={(runId) => navigate(`/runs/${runId}`)} />
      </div>

      <section className="panel projects" aria-labelledby="projects-title">
        <div className="panel-head">
          <h2 id="projects-title">Projects</h2>
          <span className="spacer" />
          {projects.data && <span className="dim mono">{projects.data.length} projects</span>}
        </div>
        {projects.loading && !projects.data && <Loading what="Loading projects" />}
        {projects.error && <ErrorBox error={projects.error} />}
        {projects.data?.length === 0 && <p className="empty">No projects yet.</p>}
        {projects.data && projects.data.length > 0 && (
          <table className="run-table">
            <thead>
              <tr>
                <th>Project</th>
                <th className="col-req">Requirement</th>
                <th>Recent runs</th>
              </tr>
            </thead>
            <tbody>
              {projects.data.map((project) => (
                <ProjectRow key={project.id} project={project} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function ProjectRow({ project }: { project: ProjectDetail }) {
  const recent = project.runs.slice(-3).reverse();
  return (
    <tr>
      <td>
        <div className="project-name">{project.name}</div>
        <div className="dim mono small">
          {project.id}
        </div>
      </td>
      <td className="col-req">
        <div className="project-requirement" title={project.requirement}>
          {project.requirement}
        </div>
      </td>
      <td>
        <div className="run-links">
          {recent.map((run) => (
            <Link key={run.id} to={`/runs/${run.id}`} className="run-link">
              <StatusBadge status={run.status} /> <code>{run.id}</code>
            </Link>
          ))}
          {recent.length === 0 && <span className="dim">no runs</span>}
        </div>
      </td>
    </tr>
  );
}
