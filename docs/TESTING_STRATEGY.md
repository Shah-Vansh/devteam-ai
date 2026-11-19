# Testing Strategy

> Status: planned. Each phase adds the tests for what it builds.

## Principles

- Tests are deterministic and free: agent tests use recorded LLM responses (fixtures), never
  live calls. A small optional "live" test group is run manually.
- Every security control has a test that tries to break it.
- Test the workflow's routing separately from the agents' content.

## Levels

| Level | What | Tools | Phase |
|---|---|---|---|
| Unit | Settings, schemas, path validation, routing functions, triage logic, token checks | pytest | 1–6 |
| Agent | Each agent with recorded LLM responses; malformed output is rejected | pytest + fixtures | 1–4 |
| MCP integration | Real MCP client ↔ server over stdio; tool discovery and calls | pytest | 2, 6 |
| Executor | `StaticOnlyExecutor` always; `E2BExecutor` with a fake, plus an optional live test | pytest | 4 |
| Workflow | Full graph with a fake LLM; every terminal state reachable; limits enforced; pause/resume | pytest | 5 |
| API | Endpoints against a temporary SQLite database | pytest + FastAPI TestClient | 7 |
| Frontend | Components and hooks | Vitest | 8 |
| End-to-end | Create project → run → approvals → report, with a mocked backend | Playwright | 8 |
| Security | Traversal, oversized files, commit without token, injection requirement, timeouts | pytest | 9 |

## CI

GitHub Actions on Ubuntu runs lint (ruff), backend tests and frontend tests on every push.
Live sandbox and LLM tests run only when their secrets are configured.

## Not tested automatically

Output quality of real LLM calls; that is measured by the benchmark in [EVALUATION](EVALUATION.md).
