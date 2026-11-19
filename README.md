# DevTeam AI

Autonomous multi-agent software engineering platform. A plain-English requirement is turned into a planned, generated, reviewed and tested Python FastAPI project by four specialised agents (Planner, Developer, Reviewer, Tester) coordinated by a LangGraph workflow, with custom MCP servers for workspace and Git access, sandboxed test execution and human approval at every risky step.

## Status

Phase 2 of 10 complete.

- **Planner agent** turns a requirement into a validated project plan. On a 10-requirement benchmark it produced valid plans 10/10 times and asked clarifying questions only where requirements were ambiguous.
- **Filesystem MCP server** provides workspace-locked file tools over stdio. Path traversal, Windows device names, drive letters, UNC paths and symlink or junction escapes are refused, and agents only get a read-only view.

Not built yet: Developer, Reviewer and Tester agents, Git MCP server, sandbox execution, workflow, API and dashboard. See `PROGRESS.md`.

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
