# DevTeam AI

Autonomous multi-agent software engineering platform. A plain-English requirement is turned into a planned, generated, reviewed and tested Python FastAPI project by four specialised agents (Planner, Developer, Reviewer, Tester) coordinated by a LangGraph workflow, with custom MCP servers for workspace and Git access, sandboxed test execution and human approval at every risky step.

## Status

Phase 7 of 10 complete.

- **Planner agent** turns a requirement into a validated project plan. On a 10-requirement benchmark it produced valid plans 10/10 times and asked clarifying questions only where requirements were ambiguous.
- **Developer and Reviewer agents** turn a plan into files written through MCP, then review them with static analysis (Python parser, ruff, bandit) plus an LLM reviewer. High-severity findings trigger at most two revisions.
- **Tester agent and sandbox execution** write pytest tests and run them in a fresh E2B microVM: packages installed from a pinned allow-list, internet switched off, results parsed from JUnit XML. Failures are triaged as bad code, bad test or environment and fixed in at most two rounds. Without a sandbox key, tests are reported as not executed, never as passed.
- **LangGraph workflow** runs every step as a graph node with bounded loops, pauses for a human (answering the Planner's questions, approving test execution) with `interrupt()`, and saves a checkpoint after every step in SQLite, so a paused run can be resumed later from another process. Every run ends in a defined state.
- **Git MCP server and commit approval**: after tests pass, the run pauses to show the files and commit message. The commit only happens with a one-time token signed after your approval and bound to exactly the files you saw; anything edited afterwards blocks it. Runs end in `SUCCESS` with a local commit, or `NOT_COMMITTED`.
- **HTTP API and database**: FastAPI with 15 endpoints to create projects, start runs, answer approvals, cancel, and read files, reviews, tests and reports; live progress as Server-Sent Events; SQLite with SQLAlchemy and Alembic migrations. Runs continue in the background, and a paused run can be approved even after the API restarts.
- **Filesystem MCP server** provides workspace-locked file tools over stdio. Path traversal, Windows device names, drive letters, UNC paths and symlink or junction escapes are refused, and agents only get a read-only view.

Not built yet: the dashboard (React). See `PROGRESS.md`.

## Quick start

Requires Python 3.12+ (developed on 3.14).

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
Copy-Item .env.example .env   # then fill in LLM_PROVIDER, LLM_API_KEY, LLM_MODEL
```

Run the tests (no network needed):

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

Plan a project:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli plan "Build a todo API with create, list and delete"
```

Plan, write, review and test a project (files go to `workspaces/`, run records to `data/runs/`; it asks before running tests in the sandbox):

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli build "Build a todo API with create, list and delete"
```

A run pauses to ask the Planner's questions, before running tests, and before committing. Type `later` to leave it paused, then:

```powershell
..\.venv\Scripts\python.exe -m app.cli status <run-id>
..\.venv\Scripts\python.exe -m app.cli resume <run-id>
```

Start the API (then open http://127.0.0.1:8000/docs):

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.api
```

Start the Filesystem MCP server and watch it refuse attack paths:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli fs-demo
```

Run the Planner benchmark:

```powershell
.\.venv\Scripts\python.exe eval\run_planner_benchmark.py
```

## Planned stack

- **Backend:** Python 3.14, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite
- **Agents:** LangGraph, provider-agnostic LLM client (Groq to start)
- **Tools:** custom MCP servers (filesystem, Git) built with the official Python MCP SDK
- **Execution:** remote microVM sandbox for generated code (never runs on the host)
- **Frontend:** React, TypeScript, Vite
- **Testing:** pytest, Vitest, Playwright

## Documentation

- [Project overview](docs/PROJECT_OVERVIEW.md)
- [System architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Agent design](docs/AGENT_DESIGN.md)
- [MCP architecture](docs/MCP_ARCHITECTURE.md)
- [Execution sandbox](docs/EXECUTION_SANDBOX.md)
- [Database schema](docs/DATABASE_SCHEMA.md)
- [API design](docs/API_DESIGN.md)
- [Security design](docs/SECURITY_DESIGN.md)
- [Testing strategy](docs/TESTING_STRATEGY.md)
- [Evaluation](docs/EVALUATION.md)
- [Technology decisions](docs/TECHNOLOGY_DECISIONS.md)
- [Development roadmap](docs/DEVELOPMENT_ROADMAP.md)
- [Architecture decision records](docs/adr/)

## Configuration

All configuration lives in one `.env` file at the repository root, shared by backend and frontend. Copy `.env.example` to `.env` and fill in the keys.

On Groq's free tier, set `LLM_REASONING_EFFORT=low`: it leaves more of the 8,000 tokens-per-minute budget for the generated code.
