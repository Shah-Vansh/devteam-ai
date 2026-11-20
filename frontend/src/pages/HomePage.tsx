import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectDetail } from "../api/types";
import { ErrorBox, Loading, StatusBadge } from "../components/common";
import { useAsync } from "../hooks/useAsync";

const MAX_REQUIREMENT = 4000;

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
    <form className="panel" onSubmit={submit} aria-labelledby="new-project">
      <h2 id="new-project">New project</h2>
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
      </label>
      <label className="field tight">
        <span>Requirement</span>
        <textarea
          rows={5}
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
          placeholder="Build a todo API with create, list, mark as done and delete"
          aria-describedby="requirement-count"
          required
        />
      </label>
      {/* Outside the label, so the field's accessible name stays "Requirement". */}
      <p id="requirement-count" className={`hint counter ${tooLong ? "error" : ""}`}>
        {requirement.length} / {MAX_REQUIREMENT}
      </p>
      <label className="field">
        <span>Project type</span>
        <select disabled value="fastapi">
          <option value="fastapi">Python FastAPI service</option>
        </select>
      </label>
      <div className="actions">
        <button
          type="submit"
          className="primary"
          disabled={busy || !name.trim() || !requirement.trim() || tooLong}
        >
          {busy ? "Starting…" : "Create and start"}
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
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
    <div className="home">
      <NewProjectForm onStarted={(runId) => navigate(`/runs/${runId}`)} />
      <section className="panel" aria-labelledby="projects-title">
        <h2 id="projects-title">Projects</h2>
        {projects.loading && !projects.data && <Loading what="Loading projects" />}
        {projects.error && <ErrorBox error={projects.error} />}
        {projects.data?.length === 0 && <p className="muted">No projects yet.</p>}
        <ul className="projects">
          {projects.data?.map((project) => (
            <ProjectRow key={project.id} project={project} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function ProjectRow({ project }: { project: ProjectDetail }) {
  const latest = project.runs.at(-1);
  return (
    <li>
      <div className="project-name">{project.name}</div>
      <div className="project-requirement muted">{project.requirement}</div>
      <div className="project-runs">
        {project.runs
          .slice(-3)
          .reverse()
          .map((run) => (
            <Link key={run.id} to={`/runs/${run.id}`} className="run-link">
              <StatusBadge status={run.status} /> <code>{run.id}</code>
            </Link>
          ))}
        {!latest && <span className="muted">no runs</span>}
      </div>
    </li>
  );
}
