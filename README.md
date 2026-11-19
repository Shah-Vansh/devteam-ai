# DevTeam AI

Autonomous multi-agent software engineering platform. A plain-English requirement is turned into a planned, generated, reviewed and tested Python FastAPI project by four specialised agents (Planner, Developer, Reviewer, Tester) coordinated by a LangGraph workflow, with custom MCP servers for workspace and Git access, sandboxed test execution and human approval at every risky step.

## Status

Phase 0 — research, planning and architecture. No application code yet.

## Planned stack

- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite
- **Agents:** LangGraph, provider-agnostic LLM client
- **Tools:** custom MCP servers (filesystem, Git) built with the official Python MCP SDK
- **Execution:** remote microVM sandbox for generated code (never runs on the host)
- **Frontend:** React, TypeScript, Vite
- **Testing:** pytest, Vitest, Playwright

Progress is tracked in `PROGRESS.md` once Phase 1 starts.
