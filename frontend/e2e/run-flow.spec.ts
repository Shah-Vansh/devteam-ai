import { expect, type Page, type Route, test } from "@playwright/test";

/**
 * The main user journey against a mocked API: create a project, watch the run, approve
 * test execution, approve the commit, read the report. The mock is a small state machine
 * that moves the run forward when the dashboard sends a decision.
 */

const API = "http://127.0.0.1:8000"; // VITE_API_BASE_URL in the root .env
const RUN_ID = "20261120-120000-abcd";
const PROJECT = { id: "prj_1", name: "notes", requirement: "Build a notes API", created_at: "2026-11-20T10:00:00Z" };

type Stage = "execute" | "commit" | "done";

function run(stage: Stage) {
  const approvals = {
    execute: { kind: "execute", payload: { kind: "execute", executor: "e2b", workspace: "notes-1" } },
    commit: {
      kind: "commit",
      payload: {
        kind: "commit",
        workspace: "notes-1",
        files: ["app/main.py", "tests/test_notes.py"],
        message: "Add notes-api\n\nA notes API.\n",
      },
    },
  } as const;
  const pending =
    stage === "done"
      ? null
      : {
          id: `apr_${stage}`,
          run_id: RUN_ID,
          status: "pending",
          answer: null,
          created_at: "",
          decided_at: null,
          ...approvals[stage],
        };
  return {
    id: RUN_ID,
    project_id: PROJECT.id,
    status: stage === "done" ? "SUCCESS" : "PAUSED",
    current_step: stage === "done" ? "commit" : "write_tests",
    review_status: "pass",
    test_status: stage === "execute" ? null : "PASSED",
    review_rounds: 0,
    fix_rounds: 0,
    workspace: "notes-1",
    model: "openai/gpt-oss-120b",
    llm_calls: 4,
    input_tokens: 6500,
    output_tokens: 4600,
    commit_sha: stage === "done" ? "ac22432ccf0000000000000000000000000000aa" : null,
    error: null,
    started_at: "2026-11-20T10:00:00Z",
    finished_at: null,
    pending_approval: pending,
  };
}

function report(stage: Stage) {
  const tests =
    stage === "execute"
      ? null
      : {
          round: 1,
          executor: "e2b",
          status: "PASSED",
          passed: 2,
          failed: 0,
          errors: 0,
          skipped: 0,
          duration_ms: 13400,
          detail: "",
          triage: null,
          cases: [
            { name: "tests/test_notes.py::test_create", outcome: "passed", message: "" },
            { name: "tests/test_notes.py::test_get_missing", outcome: "passed", message: "" },
          ],
        };
  return {
    run: run(stage),
    steps: [
      { agent: "plan", round: 1, status: "RUNNING", summary: "plan: notes-api, 4 files", finished_at: null },
      { agent: "develop", round: 1, status: "RUNNING", summary: "wrote 4 files", finished_at: null },
      { agent: "review", round: 1, status: "RUNNING", summary: "review 1: pass", finished_at: null },
      { agent: "write_tests", round: 1, status: "RUNNING", summary: "wrote tests/test_notes.py", finished_at: null },
    ],
    final_review: { round: 1, verdict: "pass", summary: "All features present.", findings: [] },
    final_tests: tests,
    files: [{ path: "app/main.py", size_bytes: 120 }],
    usage_by_agent: [
      { agent: "developer", calls: 1, input_tokens: 1400, output_tokens: 1300 },
      { agent: "planner", calls: 1, input_tokens: 1100, output_tokens: 1300 },
    ],
  };
}

async function mockApi(page: Page) {
  let stage: Stage = "execute";
  const decisions: unknown[] = [];
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  // Only the backend origin: a pattern like "**/api/**" would also catch Vite's own
  // source modules (/src/api/client.ts) and the app would never load.
  await page.route(`${API}/api/**`, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname;
    if (path === "/api/health") {
      return json(route, { status: "ok", executor: "e2b", model: "openai/gpt-oss-120b", llm_configured: true, llm_error: null, git_available: true });
    }
    if (path === "/api/projects" && method === "POST") return json(route, PROJECT, 201);
    if (path === "/api/projects") return json(route, []);
    if (path === `/api/projects/${PROJECT.id}/runs`) return json(route, { run_id: RUN_ID, status: "RUNNING" }, 202);
    if (path === `/api/runs/${RUN_ID}`) return json(route, run(stage));
    if (path === `/api/runs/${RUN_ID}/report`) return json(route, report(stage));
    if (path === `/api/runs/${RUN_ID}/events`) {
      // An event stream that ends at once; the dashboard re-reads the run on its own.
      const body = 'id: 1\nevent: log\ndata: {"message": "tester: writing tests"}\n\n';
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    }
    if (path.startsWith("/api/approvals/") && method === "POST") {
      decisions.push(route.request().postDataJSON());
      stage = stage === "execute" ? "commit" : "done";
      return json(route, { id: path.split("/").pop(), status: "approved" });
    }
    return json(route, { error: { code: "NOT_FOUND", message: `no mock for ${path}`, details: {} } }, 404);
  });
  return { decisions };
}

test("create a project, approve execution and commit, read the report", async ({ page }) => {
  const { decisions } = await mockApi(page);
  await page.goto("/");
  await expect(page.getByText("sandbox: e2b")).toBeVisible();

  await page.getByLabel("Name").fill("notes");
  await page.getByLabel("Requirement").fill("Build a notes API");
  await page.getByRole("button", { name: "Create and start" }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${RUN_ID}$`));

  // Agent cards built from the steps
  await expect(page.getByRole("article", { name: "Reviewer" })).toContainText("review 1: pass");

  // First pause: test execution
  await expect(page.getByRole("heading", { name: "Run the generated tests?" })).toBeVisible();
  await page.getByRole("button", { name: "Run tests" }).click();

  // Second pause: commit, with the message editable
  await expect(page.getByRole("heading", { name: "Tests passed. Commit these files?" })).toBeVisible();
  await expect(page.getByText("tests/test_notes.py", { exact: true })).toBeVisible();
  await page.getByLabel("Commit message").fill("First version of the notes API");
  await page.getByRole("button", { name: "Commit", exact: true }).click();

  await expect(page.getByText("Committed ac22432ccf")).toBeVisible();
  expect(decisions).toEqual([
    { decision: "approve" },
    { decision: "approve", message: "First version of the notes API" },
  ]);

  await page.getByRole("link", { name: "Report" }).click();
  await expect(page.getByText("Reviewed, tested in the sandbox and committed.")).toBeVisible();
  await expect(page.getByRole("cell", { name: "tests/test_notes.py::test_get_missing" })).toBeVisible();
});

test("shows the API's error when starting a run is refused", async ({ page }) => {
  await mockApi(page);
  await page.route(`${API}/api/projects/prj_1/runs`, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "LLM_NOT_CONFIGURED", message: "LLM_API_KEY is not set in the root .env", details: {} } }),
    }),
  );
  await page.goto("/");
  await page.getByLabel("Name").fill("notes");
  await page.getByLabel("Requirement").fill("Build a notes API");
  await page.getByRole("button", { name: "Create and start" }).click();
  await expect(page.getByRole("alert")).toContainText("LLM_API_KEY is not set");
  await expect(page).toHaveURL(/\/$/);
});

test("an unknown page says so", async ({ page }) => {
  await mockApi(page);
  await page.goto("/nowhere");
  await expect(page.getByText("Page not found.")).toBeVisible();
});

test("the demo replays a recorded run without any backend", async ({ page }) => {
  // Every API call fails, as for someone who cloned the repository without keys.
  await page.route(`${API}/api/**`, (route: Route) => route.abort());
  await page.goto("/");
  await page.getByRole("link", { name: /Watch a demo run/ }).click();
  await expect(page).toHaveURL(/\/runs\/demo$/);
  await expect(page.getByRole("note")).toContainText("replayed in your browser");

  await page.getByRole("button", { name: "Run tests" }).click({ timeout: 30_000 });
  await page.getByRole("button", { name: "Commit", exact: true }).click({ timeout: 30_000 });
  await expect(page.getByText(/Committed 35bda9da6c/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Pipeline").getByLabel("Commit: passed", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Workspace" }).click();
  await expect(page.getByLabel("Contents of app/main.py")).toBeVisible();
  await page.getByRole("link", { name: "Report" }).click();
  await expect(page.getByText("8/8 passed · e2b")).toBeVisible();
  await page.getByRole("button", { name: "Replay demo" }).click();
  await expect(page.locator(".run-title .badge")).toHaveText("running");
});
