import type {
  Approval,
  Decision,
  FileEntry,
  GitInfo,
  Health,
  Preview,
  Project,
  ProjectDetail,
  Report,
  Review,
  Run,
  TestRun,
  Usage,
} from "./types";

import { withDemo } from "../demo/demo";

// Only VITE_ variables from the root .env are visible here (never secrets).
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

/** An error from the API, in its one error shape: {"error": {code, message, details}}. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", `The backend at ${API_BASE_URL} is not reachable.`);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string; details?: object } })
      ?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "HTTP_ERROR",
      error?.message ?? `Request failed with status ${response.status}`,
      (error?.details as Record<string, unknown>) ?? {},
    );
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const baseApi = {
  health: () => request<Health>("/api/health"),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`),
  createProject: (name: string, requirement: string) =>
    post<Project>("/api/projects", { name, requirement }),
  startRun: (projectId: string) =>
    post<{ run_id: string; status: string }>(
      `/api/projects/${encodeURIComponent(projectId)}/runs`,
    ),
  getRun: (id: string) => request<Run>(`/api/runs/${encodeURIComponent(id)}`),
  cancelRun: (id: string) =>
    post<{ run_id: string; status: string }>(`/api/runs/${encodeURIComponent(id)}/cancel`),
  decide: (approvalId: string, decision: Decision) =>
    post<Approval>(`/api/approvals/${encodeURIComponent(approvalId)}`, decision),
  files: (id: string) => request<FileEntry[]>(`/api/runs/${encodeURIComponent(id)}/files`),
  fileContent: (id: string, path: string) =>
    request<{ path: string; content: string }>(
      `/api/runs/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(path)}`,
    ),
  reviews: (id: string) => request<Review[]>(`/api/runs/${encodeURIComponent(id)}/reviews`),
  tests: (id: string) => request<TestRun[]>(`/api/runs/${encodeURIComponent(id)}/tests`),
  git: (id: string) => request<GitInfo>(`/api/runs/${encodeURIComponent(id)}/git`),
  report: (id: string) => request<Report>(`/api/runs/${encodeURIComponent(id)}/report`),
  eventsUrl: (id: string) => `${API_BASE_URL}/api/runs/${encodeURIComponent(id)}/events`,
  archiveUrl: (id: string) => `${API_BASE_URL}/api/runs/${encodeURIComponent(id)}/archive`,
  preview: (id: string) => request<Preview>(`/api/runs/${encodeURIComponent(id)}/preview`),
  startPreview: (id: string) => post<Preview>(`/api/runs/${encodeURIComponent(id)}/preview`),
  stopPreview: (id: string) => post<Preview>(`/api/runs/${encodeURIComponent(id)}/preview/stop`),
  usage: () => request<Usage>("/api/usage"),
};

/** The API, with the demo run (/runs/demo) answered from a recording in the browser. */
export const api = withDemo(baseApi);
