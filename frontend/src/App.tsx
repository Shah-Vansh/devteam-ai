import { Link, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
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
        backend not reachable
      </span>
    );
  }
  if (!health.data) return null;
  const h = health.data;
  return (
    <span className="health" role="status" title={h.llm_error ?? undefined}>
      sandbox: {h.executor} · model: {h.model ?? "none"}
      {!h.llm_configured && <strong className="error"> · LLM not configured</strong>}
    </span>
  );
}

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          DevTeam AI
        </Link>
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
          <Route path="*" element={<p className="panel">Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
