# DevTeam AI

A multi-agent system that turns a plain-English requirement into a working, tested and committed
Python FastAPI service. Four specialised agents (Planner, Developer, Reviewer, Tester) are
coordinated by a LangGraph workflow. They reach files and Git only through custom MCP servers,
generated code runs only in a remote microVM sandbox, and a human approves every risky step:
running code and committing it.

Status: complete (10 phases); see [PROGRESS.md](PROGRESS.md).

## What a run does

1. **Plan:** the Planner turns the requirement into a validated plan: files, tasks, assumptions,
   and up to three questions where the requirement is genuinely ambiguous. You can answer them or
   keep the Planner's assumptions.
2. **Develop:** the Developer writes the planned files in small batches. Workflow code writes them
   through the Filesystem MCP server; the agent itself has no write access.
3. **Review:** static analysis (Python's parser, ruff, bandit, a dependency check) and an LLM
   reviewer check the code against the plan. High-severity findings trigger at most two revisions.
   The verdict is computed from the findings, so code cannot talk the reviewer into a pass.
4. **Test:** the Tester writes pytest tests. **You approve** sending them to the sandbox: a fresh
   E2B microVM, packages from a pinned allow-list, internet switched off before the tests run.
5. **Fix:** failures are triaged as bad code, bad test or environment and sent to the right agent,
   at most two rounds. Fixed code is reviewed again.
6. **Commit:** **you approve** the files and message. The Git MCP server only commits with a
   one-time token signed after your approval and bound to exactly the files you saw.

Every run ends in a defined state: `SUCCESS`, `NOT_COMMITTED`, `FAILED_REVIEW`, `FAILED_TESTS`,
`NOT_EXECUTED`, `ERROR` or `CANCELLED`. Review status and test status are reported separately: a
passed review never counts as passed tests.

## Results

First end-to-end benchmark run (`gpt-oss-120b` on Groq, E2B sandbox), reported as measured:

- 3 of the 5 cases that could run reached `SUCCESS`. All three easy requirements succeeded with
  26/26 generated tests passing, each in about two minutes with 4–5 LLM calls.
- One medium case failed its tests and then failed triage; one hit the free tier's daily token
  limit. Cases 6–10 are not measured yet. Details: [docs/EVALUATION.md](docs/EVALUATION.md).
- A run driven entirely from the dashboard (form, two approvals by click) passed 7/7 tests and
  committed.

Tests: 330 backend tests, 50 frontend unit tests and 3 Playwright end-to-end tests, all offline.
GitHub Actions runs them on every push on Linux, with Python 3.12 and 3.14.

## Quick start (Windows)

Requires Python 3.12+, Node.js 22+ and git.

```powershell
git clone https://github.com/Shah-Vansh/devteam-ai.git
cd devteam-ai
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

The setup script checks the tools, creates `.venv`, installs the backend and dashboard, and
creates `.env` from `.env.example`. Then add two keys to `.env`:

- `LLM_API_KEY`: a Groq API key (https://console.groq.com/keys). Model and other defaults are
  already set.
- `E2B_API_KEY`: an E2B API key (https://e2b.dev/dashboard). Without it the system still runs, but
  reports tests as `NOT_EXECUTED`, never as passed.

Start the API and the dashboard (each in its own window; the dashboard opens in your browser):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

On Linux or macOS use `bash scripts/setup.sh`, then start `python -m app.api` in `backend/` and
`npm run dev` in `frontend/`.

## Using it

**Dashboard** at http://localhost:5173, a dark, IDE-style interface:

- **Pipeline:** every run is shown as a CI pipeline (Plan → Develop → Review → Write tests →
  Approve run → Sandbox → Fix loop → Approve commit → Commit). The working stage pulses, the
  approval gates light up when they need you, and loops show their count.
- **Live:** the four agents with their current step, the approval gates, and a terminal-style
  log with timestamps and colour per agent.
- **Workspace:** a code editor view with a folder tree, syntax-highlighted code, a Problems panel
  with the review findings (click one to jump to the line), and source control with the commit.
- **Report:** verdict, separate review and test gauges, every test case, token usage per agent,
  and a timeline of the steps.

**Command line**, from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m app.cli build "Build a todo API with create, list and delete"
..\.venv\Scripts\python.exe -m app.cli status <run-id>
..\.venv\Scripts\python.exe -m app.cli resume <run-id>
..\.venv\Scripts\python.exe -m app.cli plan "Build a todo API"
..\.venv\Scripts\python.exe -m app.cli fs-demo
```

`build` asks at each pause; answering `later` leaves the run paused, and `resume` continues it,
even in a new terminal. `fs-demo` starts the Filesystem MCP server and shows it refusing attack
paths.

**HTTP API** at http://127.0.0.1:8000, interactive docs at http://127.0.0.1:8000/docs.

Generated projects are written to `workspaces/<project>-<id>/`, each with its own git history.
Run records go to the database in `data/`.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm test
npm run test:e2e
```

End-to-end tests use the installed Microsoft Edge locally and Chromium in CI. The live benchmark
uses Groq and E2B quota: `..\.venv\Scripts\python.exe ..\eval\run_benchmark.py --reasoning-effort low`
from `backend/`.

## Tech stack

- **Agents and workflow:** LangGraph (StateGraph, `interrupt()`, SQLite checkpointer), Pydantic
  structured output, a provider-agnostic LLM client (Groq `gpt-oss-120b` by default)
- **Tools:** two MCP servers (filesystem, Git) on the official Python MCP SDK, over stdio
- **Execution:** E2B microVMs; static analysis with `ast`, ruff and bandit
- **Backend:** FastAPI, Server-Sent Events, SQLAlchemy 2.0, Alembic, SQLite
- **Frontend:** React 19, TypeScript, Vite, React Router
- **Testing:** pytest, Vitest and Testing Library, Playwright, GitHub Actions

## Project layout

```text
backend/app/agents/        Planner, Developer, Reviewer, Tester and their prompts
backend/app/workflow/      LangGraph graph, nodes and run state
backend/app/mcp_servers/   Filesystem and Git MCP servers
backend/app/mcp_clients/   Clients for them (agents get a read-only view)
backend/app/execution/     Sandbox executors, package allow-list, constraints file
backend/app/gitops/        Git operations and commit approval tokens
backend/app/api/           FastAPI routes; services/ runs workflows in the background
backend/app/db/            SQLAlchemy models; migrations in backend/migrations/
frontend/src/              Dashboard: pages, components, hooks, typed API client
eval/                      Benchmark requirements, runners and results
docs/                      Design documents and architecture decision records
scripts/                   Setup and start scripts
```

## Security in brief

Generated code never runs on the host. Agents cannot write files, run commands or commit; workflow
code does that through MCP servers with strict path rules. Commits need a signed one-time
approval token. API keys never reach the sandbox, the MCP servers or API responses. The API only
listens on 127.0.0.1. Threat model and the tests for each threat:
[docs/SECURITY_DESIGN.md](docs/SECURITY_DESIGN.md).

## Limitations

- Single user and no authentication: a local tool, bound to localhost.
- Generates Python FastAPI services only (in memory or SQLite).
- Generated code, not secrets, is sent to the LLM provider and the sandbox provider.
- LLM review and generated tests can miss bugs; review and tests are reported separately.
- On free tiers, rate limits make larger projects slow and cap the number of runs per day.

## Documentation

- [Project overview](docs/PROJECT_OVERVIEW.md) · [System architecture](docs/SYSTEM_ARCHITECTURE.md) · [Agent design](docs/AGENT_DESIGN.md)
- [MCP architecture](docs/MCP_ARCHITECTURE.md) · [Execution sandbox](docs/EXECUTION_SANDBOX.md) · [Database schema](docs/DATABASE_SCHEMA.md) · [API design](docs/API_DESIGN.md)
- [Security design](docs/SECURITY_DESIGN.md) · [Testing strategy](docs/TESTING_STRATEGY.md) · [Evaluation](docs/EVALUATION.md)
- [Technology decisions](docs/TECHNOLOGY_DECISIONS.md) · [Architecture decision records](docs/adr/) · [Demo script](docs/DEMO.md)
- [Development roadmap](docs/DEVELOPMENT_ROADMAP.md) · [Progress log](PROGRESS.md)

## Configuration

All configuration lives in one `.env` at the repository root, shared by the backend, the MCP
servers and the dashboard (only `VITE_` variables reach the browser). `.env.example` documents
every setting. Limits such as `MAX_REVIEW_ROUNDS`, `MAX_FIX_ROUNDS` and `MAX_LLM_CALLS_PER_RUN`
bound every run.
