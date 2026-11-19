# Development Roadmap

Each phase ends with passing tests, updated docs and `PROGRESS.md`, and a review before the next
phase starts. Effort is part-time.

| # | Phase | Build | Done when | Effort |
|---|---|---|---|---|
| 0 | Planning + spikes | Design docs, ADRs, sandbox spike, structured-output spike | Decisions justified; spikes answered their questions | 1.5–2 wk |
| 1 | Foundations + Planner | Repo layout, settings from root `.env`, logging, `LLMClient`, Planner agent, LLM call logging, benchmark draft | Planner returns valid plans for all benchmark requirements | 2 wk |
| 2 | Filesystem MCP | Server, client, path security, tests | Traversal attempts rejected; tools discovered and called over stdio | 1.5–2 wk |
| 3 | Developer + Reviewer | File generation through MCP, static analysis, Reviewer findings | A plan becomes files; Reviewer returns structured findings | 2–3 wk |
| 4 | Execution + Tester | `CodeExecutor`, E2B and static-only executors, test generation, triage; **command-line end-to-end milestone** | `python -m app.cli "<requirement>"` produces a report with real test results | 2 wk |
| 5 | LangGraph | StateGraph replacing the CLI loop; counters; conditional edges; `interrupt()`; SQLite checkpointer | Loops bounded; runs pause and resume; all terminal states reachable | 2 wk |
| 6 | Git MCP | Server, approval tokens, commit flow | Commit impossible without approval | 1 wk |
| 7 | Backend + DB | Models, Alembic, routers, background runs, SSE, approvals API | Full run driven over HTTP; data persists | 2 wk |
| 8 | Frontend | Four screens, SSE, approvals | Full run from the browser | 2–3 wk |
| 9 | Evaluation + hardening | Benchmark runner, security tests, failure scenarios, CI | Benchmark results recorded; security tests pass | 1.5–2 wk |
| 10 | Packaging + portfolio | Setup scripts, README, demo script, final docs | Fresh clone runs with documented steps | 1 wk |

Total: about 18–21 weeks.

## Risks

| Risk | Mitigation |
|---|---|
| Model writes broken multi-file apps | Small apps, file-by-file plan, static checks first, bounded fixes, model chosen by benchmark |
| Sandbox provider limits, cost or outage | `CodeExecutor` interface, static-only fallback, per-run timeout |
| Free-tier rate limits | Recorded fixtures in tests, call limit per run, smaller model for cheap steps |
| Scope creep | Exclusion list; new features need discussion and an ADR |
| Docs drift from code | Docs updated in the same phase as the code |

## Learning roadmap

| Phase | Topics |
|---|---|
| 0 | Architecture trade-offs, ADRs, threat modelling, container vs microVM isolation |
| 1 | Structured outputs, prompt design, pydantic-settings, LLM error handling and retries |
| 2 | MCP protocol, stdio transport, JSON Schema, path security on Windows |
| 3 | Code-generation prompts, ASTs, linting, security scanning |
| 4 | Sandbox SDKs, isolation, JUnit XML, failure triage |
| 5 | StateGraph, reducers, conditional edges, interrupts, checkpointing |
| 6 | Safe subprocess use, approval tokens |
| 7 | Alembic migrations, background tasks, SSE, dependency injection |
| 8 | Vite, typed API clients, consuming SSE, custom hooks |
| 9 | Benchmark design, security testing, CI |
| 10 | Documentation, demo, explaining the system in interviews |
