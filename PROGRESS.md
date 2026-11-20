# Progress

| Phase | Status |
|---|---|
| 0 Planning + spikes | Done (2026-11-19) |
| 1 Foundations + Planner | Done (2026-11-19) |
| 2 Filesystem MCP | Done (2026-11-19) |
| 3 Developer + Reviewer | Done (2026-11-19) |
| 4 Execution + Tester | Done (2026-11-19) |
| 5 LangGraph | Done (2026-11-19) |
| 6 Git MCP | Done (2026-11-20) |
| 7 Backend + DB | Done (2026-11-20) |
| 8 Frontend | Done (2026-11-20) |
| 9 Evaluation + hardening | Not started |
| 10 Packaging + portfolio | Not started |

## Phase 8 — React dashboard

Done:

- `frontend/`: Vite 8 + React 19 + TypeScript 7 (strict) + React Router 7, plain CSS with light
  and dark themes and a narrow-window layout.
- Four screens: Projects (new project form + list), Run Live (agent cards, counters, approval
  panel, live feed, cancel), Workspace (files, code, findings, git), Report (verdict, review and
  tests separately, triage, LLM usage, steps).
- Typed API client with one error class; `useAsync` and `useRunEvents` hooks.
- Backend: `GET /api/runs/{id}/git` (status and history through the Git server's read tools).
- 28 frontend tests (Vitest + Testing Library); backend still 308 tests.

Live verification:

| Check | Result |
|---|---|
| Dashboard against the real API (Vite dev server and `python -m app.api`) | Project list with earlier runs and their statuses; health line (e2b sandbox, model) |
| New run started from the form and approved by clicking (notes API, `gpt-oss-120b`) | Live: SSE connected, agent cards switched to *working* and *done*, approval panels for execution and commit. `SUCCESS`: E2B 7/7 tests passed, commit `ac22432`, 4 LLM calls, about 11,000 tokens |
| Workspace and Report tabs | File tree with finding counts, code viewer, git status and history; review and test status shown separately, every test case, LLM usage per agent, steps |
| Narrow window and dark mode | Agent cards in two columns; dark theme readable |

Issues found and fixed:

- The requirement field's character counter was inside its `<label>`, so its accessible name
  became "Requirement 0 / 4000" (found by a test that looks fields up by label, as a screen
  reader would).
- jsdom 31 needs Node 22.22+; this machine has 22.13, so jsdom is pinned at 29.
- Steps that log nothing (`prepare_commit`) showed the previous step's line as their summary.
- The git panel labelled a clean repository "passed"; it now says "clean".

Not done (by design or carried over):

- Playwright end-to-end tests move to Phase 9 with CI.
- No authentication (single-user, local).

## Phase 7 — Backend API and database

Done:

- `app/db/`: SQLAlchemy 2.0 models for the 10 tables, sessions (SQLite with foreign keys and
  WAL), Alembic migration `0001`, applied at startup.
- `app/services/`: `RunManager` (background runs, approvals, cancel, restart recovery),
  `EventBroker` (per-run event history and live subscribers), idempotent state-to-database sync,
  `Runtime` (graph with SQLite checkpointer and MCP clients for the API's lifetime).
- `app/api/`: FastAPI app with the 15 documented endpoints, one error format, request ids,
  CORS, `python -m app.api` on 127.0.0.1:8000.
- Workflow: `advance` streams node updates (used by the API and the CLI); each LLM call is logged
  in the state; the commit token's hash is kept for the `approvals` table.
- 308 tests in total (13 new API tests: full run over HTTP, approvals, cancel while paused and
  while running, event replay, restart with a paused run, crash recovery, migrations vs models).

Live verification:

| Check | Result |
|---|---|
| API startup | Migration `0001` applied to `data/devteam.db`; Filesystem and Git MCP servers started; `/api/health`: executor e2b, model gpt-oss-120b, git available |
| Run driven over HTTP (todo API, `gpt-oss-120b`) | `SUCCESS` in 64 s: plan, develop, review (pass), tests written, execution approved via `/api/approvals`, E2B 8/8 passed, commit approved, commit `234e7e8`; 4 LLM calls, about 12,000 tokens |
| Database after the run | Run, 2 approvals (commit row holds only a token hash), test run with 8 cases, 6 tracked files, 4 LLM-call rows, 9 agent steps |
| Event stream | 11 `log`, 9 `step`, 2 `approval_required`, 2 `approval_decided`, 1 `finished` |

Issues found by the live run and fixed:

- The request's database session committed during FastAPI's dependency cleanup, which runs after
  the response is sent; starting a run right after creating its project returned
  `PROJECT_NOT_FOUND`. Writes now commit before responding (regression test added).
- A large structured answer (a test suite) was rejected by the provider's schema check twice in a
  row; invalid output is now retried twice instead of once.

Not done (by design or carried over):

- No authentication (single-user, bound to localhost).
- One active run per project; several projects can run at once and share the MCP connections.
- Runs that were mid-step when the API stopped are marked `ERROR`, not resumed automatically.

## Phase 6 — Git MCP server and commit approval

Done:

- `app/gitops/approval.py`: one-time commit tokens (HMAC-SHA256, per-start secret, workspace,
  content digest, nonce, 10-minute expiry; constant-time comparison).
- `app/gitops/repo.py`: initialise, status, commit, history. Fixed argument lists, explicit
  repository paths (never the outer checkout), user config and hooks ignored, exact line endings,
  validated messages, no remotes.
- `app/mcp_servers/git/` and `app/mcp_clients/git.py`: Git MCP server over stdio; the client
  creates the secret, passes it only to the server process and signs tokens. Shared client base
  class in `app/mcp_clients/base.py`.
- Workflow: `prepare_commit` (records the digest of the files shown) → `approve_commit` (pause)
  → `commit`. New terminal states `SUCCESS` and `NOT_COMMITTED`; a commit refused by the Git
  server (for example `CONTENT_CHANGED`) ends as `NOT_COMMITTED`.
- CLI: commit prompt (yes, no, cancel, later, or a new first line for the message); optional
  `COMMIT_AUTHOR_NAME` / `COMMIT_AUTHOR_EMAIL`.
- ADR 0011; threats T13 (wrong repository) and T14 (content changed after approval) added.
- 295 tests in total (41 new), no network needed; ruff clean.

Live verification:

| Check | Result |
|---|---|
| Commit through the real Filesystem and Git MCP servers (child processes) on the Phase 5 todo project (9/9 tests passed), which lives inside this project's own checkout | Status before init `NOT_A_REPOSITORY`; commit without token refused; commit with the approved token created `de4565cef9` (12 files, author DevTeam AI); reused token refused (`TOKEN_USED`); working tree clean; the outer repository's status unchanged |
| Full run to a commit with an LLM (`gpt-oss-120b`, then `gpt-oss-20b`) | Not completed: both daily token quotas were used up mid-run. Both runs ended cleanly as `ERROR` with records saved |

Issues found and fixed during the phase:

- Design flaw caught before testing: taking the content digest inside the approval node would
  have recomputed it on resume, after any edits made during the pause. It is now a separate
  node, and a test edits a file during the pause and checks the commit is refused.
- Workspaces live inside this project's checkout, so git's upward repository search would have
  reported on the outer repository; every command now names its repository explicitly.

Not done (by design or carried over):

- A full LLM run to `SUCCESS` (quotas); repeat when the daily limits reset.
- Agents get no git tools at all, although status and history would be safe; not needed yet.

## Phase 5 — LangGraph workflow

Done:

- `app/workflow/`: the run as a LangGraph `StateGraph` with 11 nodes (`plan`, `clarify`,
  `develop`, `review`, `revise`, `write_tests`, `approve`, `run_tests`, `triage`, `fix_code`,
  `fix_tests`). It replaces the Phase 3 and 4 loops (`app/pipeline/` was removed).
- Plain-data `RunState` checkpointed to SQLite after every node (`AsyncSqliteSaver`); live
  dependencies passed as runtime context, so another process can resume a run.
- Human pauses with `interrupt()`: answering the Planner's open questions (answers trigger a new
  plan) and approving test execution; both can cancel the run.
- Code fixed after failing tests goes back through review, as in the architecture diagram;
  test-only fixes go straight back to running tests.
- `guard` turns every node failure into a terminal status; terminal states reachable and tested:
  `TESTS_PASSED`, `FAILED_REVIEW`, `FAILED_TESTS`, `NOT_EXECUTED`, `ERROR`, `CANCELLED`.
- One LLM-call limit and token totals kept in the state, so they survive pauses.
- CLI: `build` (asks at pauses; `--yes` keeps assumptions and approves), `resume <run-id>`,
  `status <run-id>`; answering `later` leaves a run paused.
- 254 tests in total (31 new, loop tests moved onto the graph), no network needed; ruff clean.

Live verification:

| Run | Model | Result |
|---|---|---|
| Todo API: start in one process, paused at approval (the prompt crashed on a Windows quirk), `status` and `resume --yes` in new processes | `gpt-oss-120b` | `TESTS_PASSED`: 9/9 generated tests passed in E2B; 5 LLM calls, about 19,000 tokens; no step redone after resume |
| JWT task API (hard) | `gpt-oss-120b` | `ERROR`: daily token quota used up (clean terminal state, record saved) |
| JWT task API (hard) | `gpt-oss-20b` | `FAILED_REVIEW`: the model could not produce valid JSON for the first file batch, twice |

Issues found and fixed:

- On Windows, input redirected from NUL reports itself as a terminal and then raises EOF at the
  prompt. EOF now leaves the run paused (regression test added).

Not done (by design or carried over):

- A live run of the hard JWT requirement, and a live fix → re-test cycle (quotas); repeat with
  `gpt-oss-120b`.
- Commit step and `SUCCESS` / `NOT_COMMITTED` (Phase 6); API and dashboard pauses (Phases 7–8).
- A developer that cannot produce the first files is reported as `FAILED_REVIEW`; a separate
  development status may be clearer.

## Phase 4 — Execution and the Tester agent

Done:

- `app/execution/`: `CodeExecutor` interface; `E2BExecutor` (fresh microVM, no env vars, pinned
  install, internet off, pytest with JUnit, kill in `finally`); `StaticOnlyExecutor`
  (`NOT_EXECUTED`, never a pass); `junit.py` (defusedxml, size limit); package allow-list and a
  40-pin `constraints.txt` generated inside E2B by `scripts/lock_sandbox_packages.py`.
- `app/agents/tester.py`: writes tests, triages failures (`bad_code` / `bad_test` /
  `environment`), fixes its own tests.
- `app/pipeline/run.py`: develop-and-review, tests, approval, execution, triage and bounded fix
  rounds; one error policy for agent steps; one LLM-call budget for the whole run.
- Static analysis now checks that imported packages are allowed and declared in
  `requirements.txt` (missing file included).
- `python -m app.cli build [--yes] "<requirement>"`: asks before running tests in the sandbox,
  saves `plan.json`, `review-N.json`, `tests-N.json` and `result.json` in `data/runs/`.
- 237 tests in total (56 new), no network needed; ruff clean.

Live verification:

| What | Verified live? |
|---|---|
| E2B executor alone: pinned install, internet off, pytest, JUnit, kill (known app, 4 tests) | Yes: 3 passed, the deliberately wrong test failed with its message, network blocked; 30 s |
| Plan → write → review → 2 revisions → review pass | Yes (`gpt-oss-20b`) |
| Tester → E2B run of generated tests | Yes: e.g. 7 passed, 3 failed in 12.6 s |
| Triage of real failures | Yes: 2 `bad_code`, 1 `bad_test` |
| Fix → re-test → pass | Not yet: the 20b model's fix was rejected as invalid JSON twice (run ended cleanly as `FAILED_TESTS`); then both models' daily quotas were used up. Covered by unit tests; to repeat with `gpt-oss-120b` |

Issues found by live runs and fixed (each with a regression test):

- A model wrote `requirements.txt` as one line with literal `\n` text, so it was a single comment
  and nothing was installed. File content with escaped newlines and no real line breaks is now
  rejected, and the new dependency check flags undeclared imports at review time.
- Triage blamed the "environment" for that missing package; the prompt now says a missing
  allowed package is `bad_code` in `requirements.txt`.
- A plan without `requirements.txt` (twice in a row from the smaller model): the plan schema now
  adds it deterministically; a missing `app/main.py` is still rejected.
- The Developer could not create a missing file during a revision; it can now create
  `requirements.txt`.
- A model re-sent earlier batches' files and the strict batch rule failed the run; re-sent
  planned files are now ignored, files outside the plan are still refused.
- A failed fix (invalid JSON) crashed the run and lost its records; agent failures after review
  now end the run as `FAILED_TESTS` (or `ERROR` for provider outages) with records kept.
- Test results were saved only after triage, so a failed triage lost them; they are saved as
  soon as the run finishes.
- Collection errors had unreadable names and triage spelled them differently; they are named
  `tests/test_x.py::(collection)` and names are matched leniently.
- pytest tried to collect `Tester`, `TestSuite`, `TestCaseResult` and `TestRound` because of
  their names; they are marked `__test__ = False`.

Not done (by design or carried over):

- A complete live fix → re-test → pass cycle (quota); repeat with `gpt-oss-120b`.
- Human approval is a CLI prompt for now; Phase 5 makes it a LangGraph `interrupt()`.
- After a code fix the code is re-tested but not re-reviewed (the diagram goes back through
  review; Phase 5 follows the diagram).

## Phase 3 — Developer, Reviewer and static analysis

Done:

- `app/schemas/code.py` (`CodeChanges`: whole files) and `app/schemas/review.py` (findings,
  report; verdict computed from severities, not chosen by the model).
- `app/analysis/static.py`: Python parser, ruff and bandit on a temporary copy, fixed arguments,
  no shell, isolated from generated config; a failing tool is reported, not fatal.
- `app/analysis/outline.py`: AST outlines (imports, routes, fields, signatures; no bodies).
- `app/agents/developer.py`: generates in batches of 4 files in task order with outlines of
  earlier files; revises only files with findings, others as outlines.
- `app/agents/reviewer.py`: reads through the read-only MCP view, merges static and model
  findings, reviews large projects in parts with outlines of the rest.
- `app/agents/common.py`: `generate_checked` (one corrective retry with the exact problem).
- `app/pipeline/develop.py`: bounded develop-and-review loop with `REVIEW_PASSED` /
  `FAILED_REVIEW`, stop reasons and the per-run LLM call limit.
- `python -m app.cli build "<requirement>"` (or `--plan plan.json`); plan and review reports
  saved to `data/runs/<workspace>/` (git-ignored).
- New settings: `LLM_MAX_OUTPUT_TOKENS`, `LLM_REASONING_EFFORT`.
- 181 tests in total (51 new), no network needed; ruff clean.

Live runs (Groq `gpt-oss-120b`):

| Requirement | Files | Result | LLM calls | Notes |
|---|---|---|---|---|
| Todo API: create, list, mark done, delete (easy) | 5 | `REVIEW_PASSED`, 1 review | 2 (+1 plan) | One medium spec finding (PATCH needs a body instead of toggling) did not block |
| Recipe API with search by ingredient (medium) | 6 | `REVIEW_PASSED`, 1 review | 2 (+1 plan) | `/recipes/search` correctly declared before `/recipes/{id}` |
| Task API with registration, JWT login, per-user tasks (hard) | 8–10 | Not completed | — | Exposed the token-budget problems below. After the fixes, a run did generate, review, revise and re-review; it then stopped on an empty revision (now handled as `FAILED_REVIEW`). The final rerun used up the free tier's daily token quota during the first review. |

Issues found by live runs and fixed (each with a regression test):

- An empty `app/__init__.py` was rejected by the `CodeChanges` schema.
- The Windows console crashed printing a non-breaking hyphen from model output.
- Errors raised inside `async with FilesystemClient(...)` came out wrapped in an
  `ExceptionGroup` by the MCP SDK, so callers could not catch them by type.
- One JSON answer could not hold a 9-file project ("max completion tokens reached"); answers cut
  off at the limit were also retried pointlessly.
- The review request for a 9-file project exceeded the 8,000 tokens-per-minute limit (HTTP 413).
- A Reviewer part rejected a valid finding about an outlined file; now any existing file may be
  cited.
- A Developer that returned no changes crashed the run; it now gets one corrective retry and then
  ends the run as `FAILED_REVIEW` with a reason.

Not done (by design or carried over):

- The hard benchmark requirement has not completed a live run yet (daily quota). Repeat in
  Phase 4 with test execution.
- LLM calls of a failed revision are not counted toward the per-run limit.
- Medium findings do not block a pass.

## Phase 2 — Filesystem MCP server

Done:

- `app/workspace/paths.py`: one set of rules for untrusted paths (relative, `/` only, no `..`,
  hidden entries, drive letters, UNC paths, NTFS streams, Windows device names, forbidden or
  control characters, unknown extensions). The Planner schema now uses the same function.
- `app/workspace/store.py`: create, read, update and list inside `<WORKSPACES_DIR>/<workspace>`,
  with a real-path containment check (symlinks and junctions), size and file-count limits,
  create-only and atomic update, and error messages without host paths.
- `app/mcp_servers/filesystem/`: MCP server (official SDK 2.x `MCPServer`) over stdio with four
  annotated tools and one result shape `{ok, data}` / `{ok: false, error_code, message}`.
- `app/mcp_clients/filesystem.py`: `FilesystemClient` (stdio or in-process) and a
  `ReadOnlyFilesystem` view for agents. Only the needed variables are passed to the server.
- `python -m app.cli fs-demo` starts the server and shows tools and refused attack paths.
- 130 tests in total (92 new), including a real stdio child process; ruff clean.

Issues found and fixed during the phase:

- The installed SDK is MCP 2.x, where `FastMCP` became `MCPServer`; docs updated.
- On Windows, opening a folder as a file raises "permission denied", not "file exists", so the
  folder check now runs before the write.
- `os.walk` lists a folder's files before its subfolders' files; `list_files` now sorts the
  full list.

Not done (by design): server lifecycle inside FastAPI with restart on crash (Phase 7); deleting
files (the workflow does not need it).

## Phase 1 — Foundations and Planner agent

Done:

- `backend/` package (`devteam-backend`) installed in editable mode into the root `.venv`.
- `app/core/config.py`: typed settings from the root `.env`; empty values become "not set";
  relative paths resolve from the repo root; secrets are `SecretStr`.
- `app/core/logging.py`: one JSON object per log line; known secrets are redacted.
- `app/llm/`: `LLMClient` interface, OpenAI-compatible client (Groq), fake client for tests,
  factory that fails fast on missing configuration. Transport errors are retried by the SDK;
  invalid structured output (including Groq's server-side schema rejections) is retried once.
- `app/schemas/plan.py`: `ProjectPlan` with path-safety and consistency validators.
- `app/agents/planner.py` and `prompts/planner_system.md`: Planner agent; requirement passed as
  tagged data; input length checked before any LLM call.
- `python -m app.cli plan "<requirement>"` prints a plan.
- 38 unit tests, no network needed; ruff clean.
- `eval/benchmark.json` (10 requirements) and `eval/run_planner_benchmark.py`.

Benchmark results (2026-11-19, Groq):

| Model | Valid plans | Retries needed | Asked questions | Avg output tokens |
|---|---|---|---|---|
| openai/gpt-oss-120b | 10/10 | 0 | 6/10 (only medium and hard cases) | 1,504 |
| openai/gpt-oss-20b | 8/10 before the retry fix, 10/10 after | 1 | 0/10 | 1,107 |

Decision: `openai/gpt-oss-120b` stays the default for the Planner. It surfaced clarifying
questions exactly where requirements were ambiguous; the 20b model never asked any.

Issues found and fixed during the phase:

- Groq rejects schema-breaking output with HTTP 400 `json_validate_failed`; the client first
  treated this as a hard error (b08 failed on both models). It is now retried like invalid JSON.
- The first prompt discouraged questions so strongly that no model asked any; reworded to allow
  up to three genuinely design-changing questions.

Not done (by design): Developer, Reviewer, Tester agents; database logging of LLM calls
(Phase 7; calls are logged as JSON lines for now).

## Phase 0 — Planning and architecture

Done:

- Design documents in `docs/` and ten ADRs in `docs/adr/`.
- Single root `.env` with `.env.example` template.
- Python 3.14 virtual environment (`.venv`, not committed). Python 3.13 was planned, but its
  local install was broken; all required libraries were confirmed to install on 3.14.
- Spike A (sandbox): pytest ran in an E2B microVM; internet was switched off after package
  installation and confirmed blocked. Details in `docs/EXECUTION_SANDBOX.md`.
- Spike B (structured output): Groq `openai/gpt-oss-120b` and `openai/gpt-oss-20b` returned valid
  `ProjectPlan` objects 12/12 times. Details in `docs/AGENT_DESIGN.md`.
- Spike code was throwaway and removed after its findings were recorded.

Not done (by design): any application code.

Open items carried into later phases:

- Constraints file for sandbox packages (Phase 4).
- Full comparison entries in `TECHNOLOGY_DECISIONS.md`, written as each technology is introduced.
- Benchmark requirements finalised and used to pick the default model (Phase 1).
