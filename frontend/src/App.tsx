import { Link, NavLink, Route, Routes } from "react-router-dom";
import { API_BASE_URL, api } from "./api/client";
import { useAsync } from "./hooks/useAsync";
import { HomePage } from "./pages/HomePage";
import { ReportPage } from "./pages/ReportPage";
import { RunLayout } from "./pages/RunLayout";
import { RunLivePage } from "./pages/RunLivePage";
import { WorkspacePage } from "./pages/WorkspacePage";

function HealthBar() {
  const health = useAsync(() => api.health(), []);
  if (health.error) {
    return (
      <span className="health bad" role="status">
        <span className="dot" /> <span className="health-text">backend not reachable</span>
      </span>
    );
  }
  if (!health.data) return null;
  const h = health.data;
  return (
    <span className="health" role="status" title={h.llm_error ?? undefined}>
      <span className={`dot ${h.llm_configured ? "on" : ""}`} />
      <span className="health-text">
        sandbox: {h.executor} · model: {h.model ?? "none"}
        {!h.llm_configured && <strong className="error"> · LLM not configured</strong>}
      </span>
    </span>
  );
}

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark">DT</span>
          <span>
            DevTeam AI <small>v1.0</small>
          </span>
        </Link>
        <nav className="topnav" aria-label="Main">
          <NavLink to="/" end>
            Projects
          </NavLink>
          <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">
            API docs
          </a>
        </nav>
        <HealthBar />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/runs/:runId" element={<RunLayout />}>
            <Route index element={<RunLivePage />} />
            <Route path="workspace" element={<WorkspacePage />} />
            <Route path="report" element={<ReportPage />} />
          </Route>
          <Route path="*" element={<p className="panel empty">Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
