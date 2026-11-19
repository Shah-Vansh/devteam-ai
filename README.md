# DevTeam AI

Autonomous multi-agent software engineering platform. A plain-English requirement is turned into a planned, generated, reviewed and tested Python FastAPI project by four specialised agents (Planner, Developer, Reviewer, Tester) coordinated by a LangGraph workflow, with custom MCP servers for workspace and Git access, sandboxed test execution and human approval at every risky step.

## Status

Phase 0 (research, planning and architecture) complete. No application code yet; Phase 1 builds the foundations and the Planner agent. See `PROGRESS.md`.

Phase 0 verified two key assumptions with throwaway experiments:

- Generated tests can run in a remote E2B microVM with internet switched off before the code runs.
- Groq-hosted models return schema-valid project plans with strict structured output.

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
